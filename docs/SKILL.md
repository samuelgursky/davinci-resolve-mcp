# DaVinci Resolve MCP Server — AI Skill Reference

This document gives AI assistants the context needed to use the DaVinci Resolve
MCP server effectively. It covers the tool landscape, page prerequisites,
common workflow patterns, error recovery, and known gotchas.

---

## What This Server Does

The DaVinci Resolve MCP server bridges AI assistants to DaVinci Resolve Studio
via its official Scripting API. You can control every aspect of a post-production
session — projects, timelines, clips, color grading, Fusion compositions, audio,
render queues, and more — through natural language.

DaVinci Resolve must be running with **Preferences > General > "External scripting
using"** set to **Local**, or set to **Network** with `RESOLVE_SCRIPT_HOST`
configured to the Resolve host IP (use `127.0.0.1` on the same machine). The
server auto-launches Resolve if it is not running, but that first connection can
take up to 60 seconds.

**Free edition.** Both of those preferences are Studio features; on the free
edition `scriptapp("Resolve")` refuses a foreign process regardless. A third
transport reaches it — a script run from **Workspace ▸ Scripts** is handed the
live `resolve` object on any edition and re-exports it over an authenticated
loopback listener. Install with `python scripts/install_resolve_bridge.py` and
start it from that menu; once running it is used automatically when external
scripting is unavailable, with no environment variable needed.
`DAVINCI_RESOLVE_BRIDGE=1` *forces* it — the bridge becomes the only transport
tried, so its faults surface directly instead of degrading to another path.
Existing tool call sites work unchanged. Two things to know when diagnosing it:

- On macOS, Resolve finds Python 3 through **`PYTHON3HOME`, then
  `/usr/local/bin/python3`** — and nowhere else, so Homebrew/pyenv/uv/conda
  interpreters simply never appear, with no error. python.org installs work
  because that installer creates `/usr/local/bin/python3`; framework-ness itself
  is not the variable (#143). The sudo-free fix is
  `launchctl setenv PYTHON3HOME "$(python3 -c 'import sys; print(sys.prefix)')"`
  — `launchctl`, not `export`, because Resolve is GUI-launched and inherits
  launchd's environment. The installer preflights both routes and ships a Lua
  canary, which always lists, so "Python not detected" is distinguishable from
  "wrong folder". The preflight is macOS-only — off macOS Resolve finds Python
  by other means, and running the check there was a false alarm (#106).
  Two follow-ups from #182 worth having in hand when a user says the menu is
  empty despite a set `PYTHON3HOME`: the prefix needs **both**
  `lib/libpython3.X.dylib` and `bin/python3` under that **unversioned** name
  (Homebrew framework builds often ship only `python3.X`, so half the check
  passes on the very interpreter people reach for), and `launchctl setenv` does
  not survive a reboot — a bridge that listed for weeks and then stopped, with
  no error anywhere, is usually that. `sudo ln -s "$(command -v python3)"
  /usr/local/bin/python3` is the persistent alternative.
- **Windows: both script folders confirmed.** `%PROGRAMDATA%` (#109) and
  `%APPDATA%` (#112) have each been shown serving the bridge on Windows 11 free
  builds. If a user reports the menu entry missing on Windows, ask whether the
  Lua canary lists — that separates "wrong folder" from "Python not detected".
- **A bridge that stops answering while its socket is `LISTENING` is a stale
  process, not a modal dialog.** Before v2.70.3 the Windows bridge could never
  detect Resolve exiting (`os.getppid()` does not change there), so it outlived
  Resolve holding the port and answering with a dead handle — and the
  `bridge_timeout` message blamed a modal dialog. On any build, the way out is
  the `shutdown` operation (`BridgeClient.bridge_shutdown()`); killing the
  process is the fallback, not the first move.
- The **control panel connects over the bridge too** (fixed in v2.70.2). It runs
  as a separate process with its own connector, so a panel that reports "Resolve
  unavailable" while tool calls work is a panel-side bug, not a broken bridge.
- The in-Resolve runtime is a **copy taken at install time**. After changing the
  repository, re-run the installer and then ask the running bridge to reload —
  it re-imports from disk in place, so Resolve does not need restarting.

The bridge is a documented in-app path rather than a licence circumvention, but
Blackmagic could close it; treat it as a supported-until-it-is-not tier.

Network scripting permits remote control of Resolve. Use Local mode when remote
access is unnecessary; otherwise restrict access with host firewall and network
controls.

**Session-start update note.** The first `resolve_control(action="get_version")`
of a session returns an `mcp` block with the cached update check
(`mcp.update` + `mcp.update_decision`). If `update_decision.action` is
`"notify"` or `"prompt"`, tell the user ONCE that a newer MCP release is
available (version + one-line pointer). Do not repeat it, do not auto-apply,
and do not treat it as an error — updates are applied by the user via
`python install.py` or the control panel's Settings page. If the user asks to
check on demand, use `resolve_control(action="mcp_update_status",
params={"force_check": true})`.

Workflow Integration plugins/scripts are a separate Resolve-hosted UI mechanism.
They are not required for this MCP server, but `docs/integrations/workflow-integrations.md`
summarizes when they are useful for optional in-Resolve panels, UIManager
scripts, and render callback companions.

OpenFX plugins are native C++ image-effect plugins, not an MCP control surface.
Use `docs/notes/openfx-notes.md` when diagnosing `insert_ofx_generator` failures or
discussing optional OFX plugin development.

LUT files are directly relevant to Color-page graph actions. Use
`docs/notes/lut-notes.md` when diagnosing `graph.set_lut` failures, validating `.cube`
files, or explaining `project_settings.refresh_luts`.

Fusion templates are relevant to Edit/Cut page insertion actions. Use
`docs/notes/fusion-template-notes.md` when diagnosing `insert_fusion_generator` or
`insert_fusion_title` failures, template paths, `.setting` files, or `.drfx`
bundles.

DCTL files are programmable color transforms/effects adjacent to LUT and OpenFX
workflows. Use `docs/notes/dctl-notes.md` when diagnosing `.dctl`/`.dctle` discovery,
ResolveFX DCTL plugin behavior, ACES DCTL IDT/ODT setup, or DCTL-as-LUT usage.

Codec plugins are native IO encode plugins that extend Deliver-page render
formats/codecs. Use `docs/notes/codec-plugin-notes.md` when diagnosing missing custom
render formats/codecs, `.dvcp.bundle` packaging, or IOPlugins install paths.

The `fuse_plugin`, `dctl`, and `script_plugin` compound tools (v2.5.0+) write
Fuse plugin source, DCTL files, and Lua/Python scripts into Resolve's install
directories. They are *authoring* tools — every other tool in this server wraps
Resolve's scripting API, while these three emit and install plugin/script
source. Status: lifecycle-verified in DaVinci Resolve Studio 20.3.2.9 for
MCP-marked install/read/list/remove, regular DCTL `refresh_luts`, ACES/Fuse
restart-required classification, Python installed-script execution, and
Python/Lua `run_inline`. Use `docs/kernels/extension-authoring-kernel.md` for the
kernel boundary map, `docs/authoring/fuse-dctl-authoring.md` for the Fuse + DCTL coverage
matrix, and `docs/authoring/script-plugin-authoring.md` for the script DSL spec and the
conversational-execution model. For hand-authoring `.setting` template files
(Edit effects/transitions/titles/generators and Fusion macros) — the format,
control catalog, thumbnail conventions, install paths, and gotchas, plus copyable
starter templates — see `docs/authoring/setting-files/`.

Extension Authoring kernel actions (v2.16.0+) are exposed through
`script_plugin`:

- `extension_capabilities`
- `probe_fuse_lifecycle(name?, kind?, install?, cleanup?)`
- `probe_dctl_lifecycle(name?, kind?, category?, install?, refresh_luts?, cleanup?)`
- `probe_script_lifecycle(name?, language?, category?, install?, execute?, cleanup?)`
- `safe_install_extension(extension_type, name, source?|kind?, dry_run?)`
- `safe_remove_extension(extension_type, name, dry_run?)`
- `refresh_or_restart_required(extension_type, category?)`
- `extension_boundary_report(include_template_matrix?)`

Key behavioral notes for `script_plugin`:
- `run_inline(source, language)` runs ad-hoc Lua/Python in Resolve and returns
  stdout + result — use this for one-off conversational queries against the
  Resolve API instead of building+installing a script.
- `language` accepts `lua`, `py`, or the human-facing aliases `python` and
  `python3`.
- `execute(name, category, language)` runs an installed script; Python stdout
  and stderr are captured, while installed Lua execution can return false from
  the Python bridge even when install/read/list/remove worked.
- Lua scripts: `fusion.Execute()` from the Python bridge is a no-op in
  Resolve 20.x — `_run_inline_lua` works around this with `RunScript` against
  a temp file plus completion-sentinel polling on `app:SetData/GetData`.
- Fuse install path on macOS is `…/DaVinci Resolve/Fusion/Fuses/` (NOT
  `Support/Fusion/Fuses/` as the SDK doc lists). The MCP path helpers handle
  this; if you're staging files manually, use the path the implementation
  emits.
- Resolve picks up new scripts without a restart; new Fuses need a restart
  to register; new DCTLs need `project_settings(action='refresh_luts')`
  (regular LUT category) or a restart (ACES IDT/ODT category).

Tool metadata (v2.17.1+) includes MCP `ToolAnnotations` for read-only,
destructive, idempotent, and external-resource hints. Treat compound tool
annotations as conservative because a single compound tool may expose both probe
and mutation actions behind its `action` parameter. Continue to prefer
`safe_*`, `dry_run`, `probe_*`, `capabilities`, and `boundary_report` actions
before mutating Resolve state.

---

## Reading A Result: The Operation Envelope

Every compound tool return carries an `_operation` block alongside its normal
payload. It answers the three questions that otherwise need a different key per
tool — did it happen, was it verified, what changed:

```json
{
  "success": true,
  "insert_frame_absolute": 86400,
  "shift_frames": 48,

  "_operation": {
    "status": "success",
    "operation": "timeline.ripple_insert",
    "execution_id": "exec_d2c123817bee",
    "verification": {
      "status": "passed",
      "checks": [{"check": "readback_verification", "passed": true, "missing_items": 0}],
      "contradiction": false
    },
    "changes": {"items_added": 3, "items_moved": 17, "items_deleted": 0}
  }
}
```

- **`status`** — `success` | `partial` | `blocked` | `failed`. `blocked` means a
  confirm gate is waiting; the payload still carries the `confirm_token` and
  `preview` to act on.
- **`verification.status`** — `passed` | `failed` | `partial` | `contradiction`
  | `unverified`. **`contradiction` is the one to stop on**: Resolve reported
  success and the readback disagrees. **`unverified` means no evidence was
  reported, not that the operation was checked and found clean** — if you need
  certainty there, go and read the state back.
- **`changes`** — the semantic delta, present only when the action declared or
  reported one. **Absent means "not reported", never "nothing changed"**, so do
  not read a missing `changes` as a no-op.
- **`warnings`** — present only when there are any.
- **`execution_id`** — correlates one call across logs and transcripts.

The envelope is namespaced under `_operation` rather than merged into the top
level because `status`, `operation`, `warnings`, `result` and `changes` are all
already domain keys on this server (a background job's `status` is `"done"`, a
confirm gate's is `"confirmation_required"`). The payload is passed through
untouched; read domain values where you always read them.

Change the shape with `setup(action="set_defaults", params={"result_envelope": "pure" | "legacy" | "dual"})`,
per call with `params={"envelope": "pure"}`, or per process with
`RESOLVE_MCP_RESULT_ENVELOPE`. `pure` returns only the envelope with the payload
nested under `result`; `legacy` adds nothing.

---

## Agent Observability: Execution Traces ("Why did the editor do this?")

Multi-step AI operations (such as detecting pauses, deleting multiple timeline
items, and verifying the result) correlate across calls into unified execution
traces. Each trace captures the user request or prompt, tool execution timing,
cumulative semantic deltas, and verification outcomes.

Example trace shape returned by `resolve_control(action="get_execution_trace")`:

```json
{
  "execution_id": "exec_8f91c7a210bc",
  "request": "Remove all pauses longer than 800ms",
  "status": "success",
  "started_at": "2026-09-04T07:30:00Z",
  "ended_at": "2026-09-04T07:30:02Z",
  "duration_ms": 2845,
  "tools": [
    {
      "tool": "media_analysis.analyze_timeline",
      "count": 1,
      "duration_ms": 821
    },
    {
      "tool": "timeline.delete_item",
      "count": 17,
      "duration_ms": 1420
    }
  ],
  "changes": {
    "items_deleted": 17
  },
  "verification": {
    "status": "passed",
    "passed": true,
    "checks": [{"check": "readback_verification", "passed": true}]
  },
  "warnings": []
}
```

### Trace Actions on `resolve_control`

- **`begin_execution(request?, execution_id?, initiator?)`**: Opens a scoped
  multi-step execution. Subsequent tool calls in the session automatically thread
  under this `execution_id` until ended.
- **`end_execution(execution_id?, verification?, status?, notes?)`**: Closes the
  active execution, finalizes timestamps and aggregated metrics.
- **`get_execution_trace(execution_id?)`** / **`get_execution(execution_id)`**:
  Fetches the trace for a specific ID, or the most recent execution if omitted.
- **`list_recent_executions(limit?)`**: Returns the recent execution traces
  (newest first, default limit 20).
- **`export_execution_report(execution_id?, format?, path?, overwrite?, include_steps?)`**:
  Writes a Markdown or JSON audit report for a trace. The default destination is
  `logs/execution-reports/<execution_id>.md`; pass `format: "json"` for
  structured output, `include_steps: false` for a shorter summary, or
  `overwrite: true` to replace an existing report.
- **`clear_executions(dry_run?)`**: Clears the in-memory execution trace buffer.
- **`inspect_operation(tool?, target_action?, target_params?)`**: Evaluates operation risk
  level (`low`, `medium`, `high`, `critical`), destructive potential, confirmation
  requirements, and blast radius scope before executing an action.
- **`list_lifecycle_hooks()`**: Returns active execution lifecycle pipeline hooks
  (`risk_classification`, `resolve_state_inspection`, `dry_run_interception`,
  `readback_verification`, `drift_detection`, `provenance_trace`).

Explicit correlation is also supported per-call: pass `params={"execution_id": ...}`
or `params={"trace_id": ...}` in any tool call to associate it with a specific trace.

Two things to know when a trace is not where you expect it. The buffer holds the
**100 most recent** executions and is in memory only — a server restart empties
it, and the on-disk `logs/execution-traces.jsonl` is the durable record.
`list_recent_executions` returns a `persistence` block naming that file and
whether it is writable; check it before concluding that nothing was traced,
since the append is best-effort and will never fail a real edit to report a
logging problem.

Recorded per step: tool, action, `duration_ms`, status, semantic deltas and
verification. **Not** recorded: parameters, file paths, clip or project names.
The only free text is the `request` string passed to `begin_execution`.

The file rotates at 8 MB, keeping one previous generation as
`execution-traces.jsonl.1`. Both are gitignored along with the rest of `logs/`.
Audit reports are separate point-in-time exports; `RESOLVE_MCP_TRACE_REPORT_DIR`
moves their default directory without moving the append-only trace log.

`path` is honoured as given — the report can be written anywhere, and the
directories are created to reach it. That is deliberate (a conform's paperwork
belongs beside the conform, not in `logs/`), so treat it the way you would any
other export destination and do not invent a path near source media. The
`execution_id` route cannot escape the report directory: it is sanitised to a
filename.

A report whose run recorded no verification checks renders **"not established
— no checks recorded"** in the Passed row, never "yes" — the same rule as
`verification.status: "unverified"` in the envelope. Do not report such a run
to the user as verified.

---

## Two Server Modes

| Mode | Entry point | Tool count | Use when |
|---|---|---|---|
| Compound (default) | `src/server.py` | 36 tools | Most workflows — keeps context lean |
| Granular (full) | `src/server.py --full` | 353 tools | Power users needing one tool per API method |

This skill document covers the **compound server** (the default). Each compound
tool accepts an `action` string and an optional `params` object.

### The advanced server (`davinci-resolve-advanced-mcp`)

The same package ships an optional third surface: an offline Node server (18
tools, typically registered as `davinci-resolve-advanced`) that edits Resolve
**files** (`.drp`/`.drt`/`.drx`) and patches the project DB — no running Resolve
required. Rule of thumb: drive a *live session* with the Python server; compute
grades, QC, conform math, and file-level edits with the advanced server, then
apply results through the live server. Full catalog: `resolve-advanced/README.md`.

Operating rules an agent must know:

- **Grade value space.** `drx` `generate`/`merge` default to `space:'ui'` —
  params are Resolve PANEL units (lift/gamma/gain/offset panel numbers,
  saturation 0–100 neutral 50). Pass `space:'drx'` only for raw internal floats
  (e.g. re-encoding decoded values). Decoded values are ground truth only for
  the calibrated native set — check the `valueFidelity` marker on `parse`
  results; per-control status is `resolve-advanced/vendor/drx-parameters/CALIBRATION-STATUS.md`.
- **Hue-axis curves.** Naive `[0,1]` point lists are canonicalized into the
  verified bezier cage automatically. Pre-wrapped lists (x outside `[0,1]`) are
  REFUSED unless `allowWrappedHueCage:true` (malformed cages can crash Resolve
  19). If a `generate`/`merge` result carries a `warnings` array, the curve was
  passed through raw and will render FLAT — tell the user, don't ship it silently.
- **Node-graph relayout** (programmatic "Cleanup Node Graph"; the UI command
  has no API). Single clip, live: `gallery_stills.grab_and_export` → advanced
  `drx(action="relayout")` → `graph.reset_all_grades` → `safe_apply_drx` with
  EXPLICIT item indices (the reset is required — a same-structure apply keeps
  the old layout). Whole project, offline: `project_db(action="relayout_node_graphs")`.
- **project_db patches** require the project CLOSED in Resolve plus
  `iConfirmProjectClosed:true`; every write auto-backs-up and read-back
  verifies. Resolve caches open projects in memory: after patching, fully QUIT
  and relaunch Resolve or the patch will not be visible.
- **Guards are load-bearing.** Advanced tools refuse rather than fabricate
  (silent-lie guards): a thrown "refused" error usually means wrong input space,
  log-encoded frames, or missing media — read the message before retrying.
  Optional native deps (`better-sqlite3`, `sharp`, ffmpeg) gate some actions;
  call the advanced `capabilities` tool for live status and install hints.

Per-domain depth for both servers lives in the kernels (`docs/kernels/`), each of
which carries an "Advanced (offline) server" section where an offline counterpart
exists. Portable skills in `.agents/skills/` (`resolve-color`, `resolve-edit`,
`resolve-conform`, `resolve-delivery`, `resolve-media-analysis`) route
craft ↔ live ↔ offline automatically when working in that domain.

The compound server also registers MCP prompts. Use `davinci_resolve_workflow`
as the compact operating brief, and use `analyze_media` as a slash-command style
entry point for source-safe project, selected-clip, bin, file, or sequence
analysis. The Analyze Media prompt executes directly by default, persists
inspectable reports/artifacts under the project analysis root, requests
`host_chat_paths` visual analysis (frames are extracted to disk and the host
chat finalizes each clip via `media_analysis(action="commit_vision", ...)`),
runs local transcription through the configured backend, and writes metadata
plus source-time Media Pool markers back to the Resolve project unless the
user opts out.

Anti-regression rule: do not silently downgrade media analysis. Source-safe
means source media stays untouched; it does not mean no visuals, no transcript,
no persisted report, no metadata writeback, or no Media Pool markers. Do not
add `include_visuals=false`, `include_transcription=false`,
`publish_metadata=false`, `timed_markers=no`, `session_only=true`, or
`dry_run=true` unless the user explicitly asks for that opt-out, the target is a
raw file path that cannot receive Resolve project writeback. The host_chat_paths
vision protocol is: `analyze_*` returns a deferred payload with absolute
`frame_paths` and a JSON schema; you must read those frames as images (Claude
Code's Read tool handles JPG/PNG natively), produce the JSON, and call
`commit_vision` for each clip. Skipping `commit_vision` leaves the run in
`pending_host_vision_analysis` — surface that explicitly; do not call the
analysis complete.

The deferred payload also includes a `host_tool_choice_hint` block. Hosts that
respect this hint pass it as `tool_choice={type:"tool", name:"media_analysis"}`
on the next API turn, hard-locking the agent into the correct next call. Hosts
that don't recognize the field ignore it — the flow is unchanged for them.

## Headless Resolve (`-nogui`)

Resolve runs without a UI, and it is **capability-identical** to a GUI session.
Measured across 238 paired observations on Studio 19.1.3.7 (see
`docs/reference/headless-cli.md` and the regenerable
`docs/reference/headless-capability-matrix.md`): **zero** capabilities work with
a UI and fail without one. Pages, render-to-disk, AAF/EDL/XML/DRT/OTIO export,
`ExportCurrentFrameAsStill`, Fusion comps, colour groups, layout presets and all
ordinary editorial behave identically.

**Capability is not stability, but stability is now partly measured too.** Ten
consecutive ProRes 422 HQ renders in one headless session, from a JPEG 2000 /
MXF OP1A source, completed with no crash, no death and no leak — marginally
faster and ~95 MB lighter than the same ten renders with a UI. What remains
untested is *sustained* encode over hours and the operator's own footage and
codec settings. Use headless freely for orchestration, edit, conform, analysis
and renders of that scale; qualify it on real footage before promising a
long-form or professional-container delivery, and keep a GUI fallback there.

**Headless is NOT immune to modal dialogs — it is worse.** It cannot *display* a
dialog, but Resolve still tries to raise one, and the call then never returns.

The canonical case, measured on a cold `-nogui` boot:
`ProjectManager.SaveProject()` on the default never-saved project named
`Untitled Project` **blocks forever** headless (no return after 45s, client
parked in `Fusion::RemoteApp::WaitPkt`), where the GUI merely returns `False`.
The project has no location and there is no `SaveProjectAs`, so Resolve wants a
Save-As dialog and waits for an answer that can never arrive. In the GUI a human
clears it in one click; headless nothing can.

**Never call `SaveProject()` without checking the project name first:**

```python
project = pm.GetCurrentProject()
if project is not None and project.GetName() != "Untitled Project":
    pm.SaveProject()      # safe: it has a location
# else: nothing to save, and headless this call blocks forever
```

`src/utils/project_cleanup.py:save_project_if_safe(pm)` does exactly this — use
it rather than calling `SaveProject` directly. And do **not** reach for headless
to dodge the GUI's save dialog; that trade makes a one-click interruption into a
dead session.

Rules:

- **Check the mode before any project switch.** `resolve_control(action="runtime_mode")`
  → `{running, headless, instances, database_attached, guidance}`. It needs no
  connection.
- **`database_attached: false` means the instance is WEDGED — stop and restart it.**
  Resolve can come up with no project database attached. It accepts connections
  and answers product, version, page and current-project queries normally, so
  every ordinary liveness check passes, while `CreateProject`/`LoadProject`
  return False forever, `SaveProject` returns None, and some calls never return
  at all. It does not recover on its own. Do not retry; quit and relaunch.
- **`headless` may be `null`.** That means "cannot be determined", not "has a UI".
  Treat `null` like `false` — take the careful path — but do not report it as fact.
- **There is no API tell.** A headless instance returns a real page from
  `GetCurrentPage()` and identical product/version strings. Anything that
  inspects the `resolve` handle to guess the mode is guessing. `runtime_mode`
  reads the process argv, which is the only place `-nogui` appears.
- **Launching:** `resolve_control(action="launch", params={"headless": true})`,
  or set `DAVINCI_RESOLVE_HEADLESS=1` to make auto-launch headless. Launching
  the other mode while an instance is already running returns
  `RESOLVE_MODE_CONFLICT` rather than starting a second one — two Resolves fight
  the singleton and have been observed to crash-loop rather than fail cleanly.
- **`instances` > 1 is a fault to report**, not a state to work around. Check for
  a render node before starting anything.
- Teardown is `resolve_control(action="quit")`; it discards the open project
  without prompting, which is what a batch process wants.

The one thing headless genuinely cannot do is anything that needs a *visible
panel* — `ExportStills` being the known case, and it fails in a panel-closed GUI
too.

## Local Control Panel

If the user asks to open, launch, or inspect the Resolve MCP control panel, run
this from the repository root:

```bash
venv/bin/python -m src.control_panel
```

The command starts the local control panel and opens the default browser. Use
`--no-open` when running in a headless context, then give the user the printed
localhost URL **exactly as printed** — it carries a per-launch bearer token in
its fragment (`#token=…`) and the panel refuses every request without it. The
panel binds loopback only (a non-loopback host is refused, no override) and is
single-user; it is an operational surface
for server status, Resolve clips, source-safe analysis jobs, preferences, and
diagnostics as those sections are added.

The **Review tab → History** button opens the timeline-history surface:
per-timeline version chain, brain-edit deltas, manual archive, and rollback.
Backed by `timeline_versioning` MCP actions; see that tool's section below for
the underlying primitives.

---

## Editorial Memory And Decision-Making

When the user asks for cutting, pacing, story shape, suspense, comedy timing, or
tonal reframing, operate like an editor, not just a metadata scanner. Use
`docs/guides/editorial-decision-guide.md` as the project-owned craft reference. The
short version: emotion and story come first, then clarity, rhythm, eye trace,
screen geography, continuity, and coverage variety.

Before analyzing or rebuilding anything, check whether the active project already
contains useful evidence:

- `media_analysis(action="coverage_report", params={"target": {...}})` — the
  pre-flight contract. Pure read; never triggers analysis. Returns per-clip
  state (analyzed / stale / missing / reuse_blocked / superseded_by_relink),
  layer presence, `source_trust` tier, and a `recommended_action`. The response
  carries an `evidence_base` summary string — **lead any editorial or color
  recommendation with that line, before the creative answer.**
- `media_analysis(action="summarize")` for project-wide rollup of warnings,
  motion distribution, and signed-report counts.
- `media_analysis(action="get_report")` when a manifest or report path is known.
- `timeline(action="list")`
- `timeline(action="get_current")`
- `timeline(action="probe_timeline_structure")`
- `timeline(action="source_range_report")`
- `timeline_markers(action="get_all")`
- `media_analysis(action="review_timeline_markers")` when marker imagery matters

Reuse prior analysis unless it is stale, incomplete, missing a modality, or
flagged `superseded_by_relink` because Resolve's source clip was replaced after
analysis ran. Coverage_report surfaces all of these in one read. Do not re-run
visual analysis just because the edit task is new if a current report already
has keyframes, motion variance, and usable visual descriptions. Add
transcription, host_chat_paths vision (followed by commit_vision), marker
review, or source range checks only when that missing evidence changes the
decision. Use `force_refresh=true` only when the user asks for a fresh read or
when cache signatures show the source, prompt, depth, or requested modality has
changed.

Source-trust filtering: `coverage_report` accepts `min_source_trust` (one of
`auto`, `filename`, `low`, `medium`, `high`). Clips below the threshold appear
in `summary.clips_needs_higher_trust` and are reported with
`below_min_source_trust=true`. Use `medium` for routine work, `high` for
shot-matching or look-development passes where confident scene/identity reads
matter.

For finished-video editorial work, scene detection and motion variance are
guardrails, not story. Use them to avoid black frames, flash frames, corrupt
ranges, and accidental cut points. Let transcript, sound events, complete
thoughts, reactions, and decisive visual frames drive the actual edit.

After creating or modifying a timeline variant, do a second pass before calling
the work done:

- `timeline(action="detect_gaps_overlaps")`
- `timeline(action="source_range_report")`
- `timeline_frame(action="capture")` at important markers and cuts
- Compare each marker name against the Resolve-rendered frame; revise the marker
  or edit if the image contradicts the plan.

Do not depend on personal, external, or workstation-specific editorial context.
For this project, keep the editorial craft reference self-contained in
`docs/guides/editorial-decision-guide.md` and keep this `SKILL.md` focused on
operational use of the MCP.

---

## Color Memory And Decision-Making

When the user asks for color correction, shot matching, look development, LUTs,
DCTLs, DRX grades, Gallery stills, or color-group workflows, use
`docs/guides/color-decision-guide.md` as the project-owned color reference.

Be explicit about the API boundary:

- Directly creatable/control surfaces: CDL values on an existing node, grade
  versions, color-group assignment, LUT assignment on existing nodes, node
  enable/cache state, LUT/DCTL assets, Gallery still import/export, and grade
  copy/export helpers.
- Opaque full-grade surfaces: copied grades, imported/exported `.drx` stills,
  and manually built Resolve node graphs. These can carry full grades, but the
  MCP applies or copies them as packages.
- Not directly creatable from structured params: new node trees, Lift/Gamma/Gain
  wheel values, log/HDR palette values, curves, qualifiers, power windows,
  tracking, Color Warper, and detailed ResolveFX/OFX parameter edits.

Before any color recommendation, run
`media_analysis(action="coverage_report", params={"target": {...},
"min_source_trust": "medium"})` (use `"high"` for shot-matching or
look-development passes). Lead the response with the returned `evidence_base`
line before the grade plan. Coverage_report surfaces relink-superseded clips
that must be re-analyzed before being graded from prior visual descriptions.

For safe color work, start with `timeline_item_color(action="grade_boundary_report")`,
`timeline_item_color(action="grade_version_snapshot")`,
`timeline_item_color(action="probe_node_graph")`, and a Resolve-rendered frame
reference for the target shot or shots. Use thumbnails, contact sheets, Gallery
stills, marker frames, or existing visual analysis reports before writing a
grade, and cite the inspected frames in the response. When the API can safely
provide them, compare matched untreated/bypass, current, and after frames at the
same timecodes, then restore the previous active version or node-enabled state
after any temporary bypass capture. Treat untreated frames as diagnostic
evidence, not as permission to discard an existing creative grade.

Prefer `safe_set_cdl` for small reversible primary corrections. `SetCDL`'s
`NodeIndex` is 1-BASED (scripting README line 6) and there is no `GetCDL`
readback — `safe_set_cdl` and `apply_look_to_items` now read the node graph's
`GetNumNodes` first and return a structured reason/diagnosis on a false
`SetCDL` instead of a bare boolean. Use DRX/stills
or grade copy only when the user accepts whole-grade replacement/transfer
semantics. Use DCTL/LUT authoring only for reusable mathematical transforms, not
as a substitute for hand-built windows, qualifiers, or tracked secondaries. Do
not apply blind/global grades unless the user explicitly asks for that. When the
user asks to build on or adjust an existing grade, preserve the current
grade/version as the starting point, create or switch to a recoverable
adjustment version, and apply only incremental changes through supported
controls. Do not reset grades, replace graphs, or apply DRX/copy-grade
whole-grade artifacts unless replacement or transfer semantics are explicitly
accepted. Distinguish Resolve's default one-node graph from an existing creative
grade; only describe a creative grade when active tools, LUTs, or other grade
state are present.

For sequence-wide looks, prefer a duplicated timeline, batch creation of
reference/current/look versions across all target clips, and one bulk Resolve
script for repeated version, group, or CDL operations. Use color groups for shared
scene-level intent only when they fit the work: group pre-clip for shared
normalization, clip versions for shot-specific matching, and group post-clip for
the creative look. Sampling can guide a first pass, but final handoff should
state the reviewed scope; short sequences should be checked shot by shot.

---

## Page Context Requirements

DaVinci Resolve is a page-based application. Certain operations only work on
specific pages. Always confirm or switch pages before calling page-sensitive tools.

| Operation category | Required page | How to switch |
|---|---|---|
| Color grading, node graphs, CDL | Color | `resolve_control(action="open_page", params={"page": "color"})` |
| Gallery stills export, `grab_and_export` | Color, Gallery panel open | `resolve_control` + open Gallery panel in Workspace menu |
| Fusion compositions (page comp) | Fusion | `resolve_control(action="open_page", params={"page": "fusion"})` |
| Timeline editing, track operations | Edit or Cut | `resolve_control(action="open_page", params={"page": "edit"})` |
| Fairlight audio | Fairlight | `resolve_control(action="open_page", params={"page": "fairlight"})` |
| Render / deliver | Deliver | `resolve_control(action="open_page", params={"page": "deliver"})` |
| Media import, storage browsing | Media | `resolve_control(action="open_page", params={"page": "media"})` |

When a tool returns an unexpected `False` or an error about context, check whether
you are on the correct page first.

---

## Tool Map

### Craft Guidance

**`knowledge`** — The editorial, colour, audio, and workflow guidance bundled with
this server, served as prose. No Resolve connection required.

Read a topic **before** a creative or destructive operation, not after. The tools will
happily execute an editorially wrong decision; this is where the reasoning lives —
measured numbers, known traps, and what each move costs to undo.

Key actions:
- `topics(category?)` — the index: topic id, one-line summary, size, sections, and
  related topics. Categories: `workflow` (task playbooks: tighten a recording, build a
  rough cut, match a grade), `guide`, `kernel` (per-surface tool maps), `reference`
  (exhaustive ledgers including this document), `repo` (contributing here)
- `get(topic, section?, inline?)` — the resolved prose. Natural aliases work
  (`"tighten"`, `"dead air"`, `"grading"`, `"conform"`). Referenced guides and kernels
  arrive inlined, so a client with no checkout of this repository still gets the
  manual, not a path to it. `section` returns one heading's subtree
- `search(query, limit?)` — ranked topics with excerpts
- `capabilities()` — topic count by category, and the corpus directories

The same index is published as the `knowledge://topics` MCP resource, so hosts that
consume resources can see what guidance exists without spending a turn.

---

### App Control

**`resolve_control`** — App-level operations.

Key actions:
- `launch` — connect to or start Resolve; call this first if any tool returns a
  "Not connected" error
- `get_version` — returns `{product, version, version_string, build, mcp}`.
  `build.unavailable_on_this_build` lists every recorded API surface this build
  does **not** have; read it before offering anything version-gated. An absence
  from that list is not a promise a method exists — most of the API has never
  been version-bisected, so `check_version_support` answers `unknown` for it,
  and `unknown` means probe with `name in dir(obj)`, never bare `hasattr`
  (constant `True` on Resolve objects)
- `check_version_support(symbol?, resolve_version?)` — is one named symbol on
  this build? Without `symbol`, the same missing-surface list `get_version`
  carries. No connection needed when `resolve_version` is passed
- `api_truth(query?)` — look up behaviorally-verified facts about quirky/unreliable
  Resolve API behavior (no connection needed); filter by substring
- `verification_stats` — readback-verification tally (verified/contradicted/
  unverified) since server start (no connection needed)
- `get_page` / `open_page(page)` — read or switch the active page
- `get_keyframe_mode` / `set_keyframe_mode(mode)`
- `get_fairlight_presets` — Resolve 20.2.2+; returns available Fairlight
  preset names
- `list/save/load/delete/import/export_user_preferences_preset` — Resolve
  21.0.4+; user-preferences presets. `load_...` is SESSION-WIDE: it swaps the
  user's global Resolve preferences, so only call it when the user asked for
  the switch. `import_...` does not activate the imported preset — follow with
  `load_user_preferences_preset`
- `quit` — terminates Resolve (destructive; confirm with user first)

**Offline timeline authoring on `timeline`** — served above the connection check:
`author_offline` writes an importable `.drt` / `.otio` / `.edl` from a clip plan when
Resolve is unreachable, and `offline_fallback_capabilities` reports whether it can. Every
not-connected error carries an `offline_alternative` block naming it. Authoring a file
does not complete a failed live operation — the timeline is not in a project until it is
imported. See `docs/kernels/timeline-conform-interchange-kernel.md`.

**Offline audio and image QC on `media_analysis`** — no Resolve connection required:
`measure_loudness`, `mix_plan` / `mix_plan_capabilities` (dialogue-anchored rough mix
with dialogue-following ducking, rendered and re-measured), and `assess_grade` /
`grade_loop` / `grade_loop_capabilities` (numeric grade-damage QC and the retry ladder
that backs a look off until it stops damaging the picture). See
`docs/kernels/audio-fairlight-kernel.md` and `docs/kernels/color-grade-kernel.md`.

**`layout_presets`** — Save, load, export, import, delete UI layout presets.
`list` (Resolve 21.0.4+) enumerates the saved preset names the other actions
take.

**`render_presets`** — Import and export render and burn-in presets.
`list_burnin` / `delete_burnin` (Resolve 21.0.4+) enumerate and remove burn-in
presets — `list_burnin` is the only way to discover the names the `DataBurnIn`
render setting and the `load_burnin_preset` actions expect.

---

### Project Management

**`project_manager`** — CRUD on projects.

Key actions: `list`, `list_attributes`, `get_current`,
`create(name, media_location_path?)`,
`load(name)`, `save`, `close`,
`delete(name)`, `import_project(path)`, `export_project(name, path)`, `archive`,
`restore`

`list_attributes` (Resolve 21.0.4+) returns `lastModifiedDate`, `creationDate`,
`notes`, and `liveCollaborationMode` per project in the current folder without
loading any of them.

Project / Database / Archive kernel actions (v2.15.0+) add guarded project
lifecycle, settings, database, preset, and archive boundary helpers:

- `project_capabilities`
- `probe_project_lifecycle`
- `probe_project_settings(keys?, try_write?, dry_run?)`
- `safe_project_create(name, media_location_path?, dry_run?)`
- `safe_project_export(name, path, with_stills_and_luts?, dry_run?)`
- `safe_project_import(path, name, dry_run?)`
- `safe_project_archive(name, path, src_media=false, render_cache=false, proxy_media=false, dry_run?)`
- `safe_project_restore(path, name, dry_run?)`
- `safe_project_delete(name, close_current?, dry_run?)`
- `safe_set_project_settings(settings, restore?, dry_run?)`
- `project_settings_snapshot(name?)`
- `database_capabilities`
- `safe_set_current_database(db_info, dry_run?, allow_switch?)`
- `preset_lifecycle_probe`
- `project_boundary_report`

Health check and declarative spec (v2.28.0+):

- `lint` — graded project health pre-flight returning `{ok, counts, issues}`.
  Issues (error / warning / info) cover: no project, no current timeline, mixed
  frame rates across timelines, empty timeline, render format unset, color
  science unmanaged, offline media, and unanalyzed clips. Composed from existing
  probes; safe read-only.
- `diff_to_spec(spec_path | spec)` — preview drift between a declarative spec and
  the live project WITHOUT mutating. Returns `{actions, diff, change_count}`.
- `plan_spec(spec_path | spec)` — the ordered action list as a dry run.
- `apply_spec(spec_path | spec, dry_run?, run_hooks?, continue_on_error?)` —
  reconcile the project toward the spec. Idempotent (re-runs are no-ops); color/
  HDR settings apply in dependency order; markers added only when absent; explicit
  `settings` override a named `color_preset`; before/after shell hooks run only
  with `run_hooks=true`. The spec is YAML or JSON:
  `{project, color_preset?, settings?, timelines:[{name, fps?, settings?, markers?}], hooks?}`.
  Note: `apply_spec` reconciles the **currently open or already-existing** project;
  creating a brand-new project from a spec depends on Resolve's `CreateProject`
  succeeding (it can return None when an unsaved project blocks the switch).

Safe project actions require `_mcp_` names and temp paths by default. Database
switching dry-runs by default because Resolve closes open projects when
switching databases. Archive source media/cache/proxy flags are rejected unless
explicitly opted in.

**`project_manager_folders`** — Navigate project folders.

Key actions: `list`, `get_current`, `create(name)`, `open(name)`, `goto_root`,
`goto_parent`

**`project_manager_database`** — Switch databases.

Key actions: `get_current`, `list`, `set_current(db_info)`

**`project_manager_cloud`** — Cloud projects (requires Resolve cloud
infrastructure; most users will not have this).

**`project_settings`** — Project metadata, settings, color groups, and misc
operations on the open project.

Key actions: `get_name`, `set_name(name)`, `get_setting(name?)`,
`set_setting(name, value)`, `get_color_groups`, `add_color_group(name)`,
`delete_color_group(name)`, `export_frame_as_still(path)`,
`load_burnin_preset(name)`, `insert_audio(media_path, ...)`,
`apply_fairlight_preset(preset_name)`,
`project_summary(include_clips?, clip_limit?)` — live structural readout
(current page, timeline count, media-pool inventory by type)

---

### Media

**`media_storage`** — Browse mounted volumes and import files.

Key actions: `get_volumes`, `get_subfolders(path)`, `get_files(path)`,
`import_to_pool(items)` — `items` is a list of file path strings

**`media_pool`** — Full Media Pool management.

Key actions: `get_root_folder`, `get_current_folder`, `set_current_folder(path)`,
`add_subfolder(name)`, `create_timeline(name)`, `import_timeline(path, options?)`,
`import_media(paths)`, `delete_clips(clip_ids)`, `move_clips(clip_ids, target_path)`,
`setup_multicam_timeline(name, clip_ids|angles, sync_mode?, include_audio?, dry_run?)`,
`get_selected`, `set_selected(clip_id)`, `export_metadata(path, clip_ids?)`

Media Pool / Ingest kernel actions (v2.8.0+) add safer agent-facing workflows:
`ingest_capabilities`, `probe_media_pool`, `probe_ingest_item`,
`safe_import_media`, `safe_import_sequence`, `safe_import_folder`,
`organize_clips`, `copy_metadata`, `normalize_metadata`,
`probe_clip_properties`, `metadata_field_inventory`, `safe_relink`,
`safe_unlink`, `link_proxy_checked`, `link_full_resolution_checked`,
`set_clip_marks`, `clear_clip_marks`, `copy_clip_annotations`,
`setup_multicam_timeline`, and
`media_pool_boundary_report`. See
`docs/kernels/media-pool-ingest-kernel.md` for the live-tested support map.

`setup_multicam_timeline` is a helper, not a native multicam API wrapper. It
creates a source-safe stacked prep timeline with one angle per video track,
optional matching audio tracks, and `stack_start`, `source_timecode`, or
explicit `record_frame` placement. Native multicam clip creation, angle
switching, and flattening remain Resolve UI workflows; see
`docs/guides/multicam-setup-guide.md`.

Note: `folder path` arguments use slash notation like `"Master/SubFolder"`.
`"Master"` or `"/"` refers to the root folder.

Address a folder either by `path` or by `folder_id` — the id `get_subfolders`
returns for each entry (v2.77.0+; the same pair works for `media_pool
add_subfolder` via `parent_path`/`folder_id` and for `media_pool
get_timeline_mattes` via `folder_path`/`folder_id`). Omit both to get the
action's default: the current folder for the `folder` tool, the root folder for
those two `media_pool` actions. An address that is supplied but does not resolve
is a `FOLDER_NOT_FOUND` / `invalid_input` error — it never quietly falls back to
the current bin.

That fallback is what these tools used to do, so treat a pre-v2.77.0 server as
unable to tell you when it answered about the wrong folder. Note also that only
`path`/`folder_path`/`folderPath` and `folder_id`/`folderId` are recognised as
addresses: any other key you invent (`id`, `bin`, `folderName`) is still
silently dropped, and the action still answers about its default folder with
`success`. Use the documented names.

**`folder`** — Operations on a specific Media Pool folder.

Key actions: `get_clips(path?|folder_id?)`, `get_subfolders(path?|folder_id?)`, `export(path?, export_path)`,
`transcribe_audio(path?, use_speaker_detection?)`, `clear_transcription(path?)`,
`perform_audio_classification(path?)`, `analyze_for_intellisearch(path?, identify_faces?, is_better_mode?)`,
`analyze_for_slate(path?, marker_color?)`, `remove_motion_blur(path?, deblur_option?)` (Resolve 21+;
the last three need AI Extras, and `remove_motion_blur` is confirm-token gated)

**`media_pool_item`** — Read/write clip metadata and properties. All actions
require a `clip_id` (the UUID returned by `GetUniqueId()`).

Key actions: `get_name`, `get_metadata(key?)`, `set_metadata(key, value)`,
`get_clip_property(key?)`, `set_clip_property(key, value)`, `get_clip_color`,
`set_clip_color(color)`, `link_proxy(proxy_path)`, `replace_clip(path)`,
`set_name(name)`, `link_full_resolution_media(path)`,
`replace_clip_preserve_sub_clip(path)`, `monitor_growing_file`,
`transcribe_audio(use_speaker_detection?)`, `clear_transcription`,
`get_transcription` (read back `{text, truncated, status, has_transcription}`;
`truncated` flags when Resolve's preview cut the text off),
`perform_audio_classification`,
`analyze_for_intellisearch(identify_faces?, is_better_mode?)`, `analyze_for_slate(marker_color?)`,
`remove_motion_blur(deblur_option?)` (Resolve 21+; AI Extras / confirm-token gated as noted above),
`get_audio_mapping`, `get_mark_in_out`, `set_mark_in_out`

**`media_pool_item_markers`** — Markers and flags on clips in the Media Pool.
All actions require a `clip_id`.

Key actions: `add(frame, color, name, note, duration)`, `get_all`, `delete_by_color(color)`,
`delete_at_frame(frame)`, `add_flag(color)`, `get_flags`, `set_name(name)`

**`media_analysis`** — Project-scoped media intelligence and guarded metadata publishing.

Media Analysis and editorial-assist actions (v2.17.0+) add source-safe planning,
report reuse, persisted analysis execution, host_chat_paths visual review
(finalized per clip via `commit_vision`), transcription, default Resolve
metadata/marker writeback, and timeline-level editorial helpers.

Key actions: `capabilities`, `install_guidance`, `resolve_output_root`, `plan`,
`coverage_report`, `analyze_file`, `analyze_clip`, `analyze_bin`,
`analyze_project`, `detect_sync_events`, `add_sync_event_markers`,
`publish_clip_metadata`, `commit_vision`, `summarize`, `get_report`,
`build_index`, `index_status`, `query_index`, `start_batch_job`,
`run_batch_job_slice`, `batch_job_status`, `list_batch_jobs`,
`cancel_batch_job`, `resume_batch_job`, `review_timeline_markers`,
`cleanup_artifacts`, `db_status`, `db_ingest`, `get_panel_state`,
`set_panel_state`, `session_start_context`, `update_clip_field`,
`update_shot_field`, `get_field_history`, `revert_field`,
`list_corrections`, `deepen`, `commit_shot_vision`, `vision_pending_sweep`,
`build_embeddings`, `find_similar`, `detect_entities`, `commit_entities`,
`list_entities`, `prepare_bin_briefing`, `commit_bin_summary`,
`detect_shot_relationships`, `commit_shot_relationships`,
`list_shot_relationships`, `strata_status`, `backfill_words`, `strata_run`,
`take_diff`, `cut_candidates`, `strata_query`, `timeline_strata`,
`plan_story_beats`, `commit_story_beats`, and `list_story_beats`.

**Cross-clip entities + bin briefing v2 (v2.44.0+).** Recurring
people/places/props across a project's media, found cheaply and confirmed
with ONE vision call per cluster:
- `detect_entities(threshold?, min_cluster_size?)` clusters the v10 CLIP
  frame vectors (build visual embeddings first), writes provisional entity
  rows + appearances, and returns a deferred payload with one
  representative frame per cluster (caps pre-checked, estimate inlined).
  The host chat reads those frames and calls
  `commit_entities(entities=[{entity_index, kind, label, description,
  confidence, merge_with?}], vision_token)` — conservative labels only
  (describe what's visible; never guess names). `merge_with` collapses
  clusters that show the same entity.
- `list_entities` returns labeled entities with per-clip/shot appearances;
  the panel's Review page shows a "Recurring across this bin" card.
- `prepare_bin_briefing` returns entities + per-clip summaries (text-only,
  no vision cost); the host writes a colleague-style markdown briefing and
  calls `commit_bin_summary(briefing, briefing_token)`, which lands in
  `memory/bin_summary.md` above the v2.0 aggregate.

**Cross-shot relationships (v2.49.0+).** Pattern recognition only (spec §4 —
no editorial suggestions): `same_setup_as` / `alt_take_of` (symmetric) and
`continues_from` (directional; the source shot continues from the target).
- `detect_shot_relationships(setup_threshold?, alt_take_threshold?,
  continues_band?, max_candidates?)` — pairwise cosine over the per-shot
  visual vectors (build visual embeddings first; raise
  `max_frames_per_clip` if shot coverage is partial), plus transcript
  continuity as a second signal for `continues_from`. Returns a deferred
  payload with a representative frame PAIR per candidate (caps pre-checked,
  two frames per candidate). Candidates live only in the detection-state
  stash until committed — re-detect replaces them.
- The host chat reads BOTH frames of each pair and calls
  `commit_shot_relationships(relationships=[{candidate_index, verdict:
  confirm|reject, relationship_type?, confidence?}], vision_token)`.
  Confirm only what the frames show; reject lookalikes. Overriding the
  suggested type is allowed. Committed rows supersede prior machine rows
  for the same pair.
- `list_shot_relationships(clip_id?, shot_uuid?, relationship_type?)` —
  current rows with clip/shot context on both ends. The shot page's
  Relationships group fills from these rows, and `plan_swap` prefers
  confirmed `alt_take_of` alternates over raw cosine (the rationale states
  which basis ranked each alternate).

**Perception strata (v2.61.0+, schema v13/v14).** A timecoded track model over
each analyzed clip — events (pause/breath/hesitation/blink/beat/downbeat/…),
sampled curves (pitch/vocal_energy/speech_rate/motion_energy/face curves),
per-word transcript rows, and story beats. Local compute only (ffmpeg + numpy;
face tier needs opencv + mediapipe); machine re-runs replace their own rows,
human rows are append-only and always win. These measure and rank — they never
decide; the editor picks.
- `strata_status(clip_id?)` — project or per-clip track inventory plus what
  this machine can run (`analyzer_capabilities`).
- `strata_run(clip_id, analyzers?)` — run prosody / beat_grid / motion_energy
  / face on one clip (default: whatever is available locally).
- `backfill_words()` — promote word timestamps already inside stored report
  blobs into queryable `transcript_words` rows; idempotent, no re-analysis.
- `take_diff(clip_a, clip_b, text?)` — align two takes on transcript words
  and diff their delivery (pace, pauses, pitch, energy). Deltas only, no
  winner.
- `cut_candidates(clip_id, time_seconds, window_seconds?, fps?, limit?)` —
  rank cut frames around an intended joint with human-readable reasons
  (blink / word-gap / pause / breath / beat / motion); missing tracks are
  reported, never treated as "no signal".
- `strata_query(clip_id?, start_seconds?, end_seconds?, match_word?, …)` —
  one queryable surface: a windowed cross-track bundle for a clip, or a
  project-wide word find with a joined ±context bundle per hit.
- `timeline_strata(timeline_name, timeline_version?, …)` — project clip
  strata through a versioned timeline's recorded placements. Snapshot frames
  are absolute record frames (start-timecode-inclusive); snapshots from
  schema v14+ carry the timeline's fps/start frame so placements also get
  timeline-relative frames and seconds.
- `plan_story_beats(clip_id)` / `commit_story_beats(clip_id, beats)` /
  `list_story_beats(clip_id)` — host-LLM pass over the transcript digest
  (the server never calls an LLM): beats are units of meaning with types
  (topic/claim/revelation/emotional/anecdote/question/callback), links, and
  supersede semantics.

**Embeddings + similarity (v2.43.0+).** Local-compute semantic search; no
vendor tokens, so nothing here touches the caps ledger. Backends are
detected, never installed (capabilities lists them with install guidance):
text = ollama serving `nomic-embed-text` or sentence-transformers; visual =
open_clip (ViT-B-32, needs torch); audio (v2.51.0+) = CLAP via
`transformers` (laion/clap-htsat-unfused, preferred) or the `laion_clap`
package — needs torch + ffmpeg.
- `build_embeddings(kinds=["text","visual","audio"]?, clip_id?)` —
  idempotent; embeds clip summaries, shot descriptions (+ deep field
  groups), transcript segments, and sampled frames (per-shot visual vector
  = mean of its frames'). `kinds=["audio"]` embeds one CLAP window per shot
  (center-cropped to ~10s, piped from the source media as raw PCM —
  read-only, no temp files) plus a clip-level mean vector; clips whose
  media is offline are reported in `skipped_missing_media`. Only re-embeds
  entities whose content changed.
- `find_similar(text=… | clip_id=… | clip_id+shot_index,
  kind="text"|"visual"|"audio", entity_types?, limit?)` — brute-force
  cosine over the project's vectors. Free-text visual queries use the CLIP
  text encoder ("cracked windshield" finds the frame); free-text audio
  queries use the CLAP text encoder ("engine revving" finds the shot).
  Results carry scores plus clip/shot/segment context.
The panel search box gains a `Semantic` toggle when a text backend is
detected. Vectors live in the per-project DB (schema v10).

**Deep shot-level vision tier (v2.42.0+).** Opt-in, estimate-first. Two
entry points share one per-shot schema (Visual / Content / Production /
Editorial / Cuttability / description / confidence):
- `depth="deep"` on any analyze action extends the deferred host-vision
  payload with `deep_shot_schema`; each `shot_descriptions` entry must carry
  the field groups. The first deep run returns `confirmation_required` with
  a token-cost estimate — re-call with `confirm_deep=true`. Caps still apply.
- `deepen(clip_id|clip_dir, shot_index?|shot_indices?)` runs the pass
  post-hoc on an already-analyzed clip. First call returns the estimate +
  `confirm_token`; re-call with the token to get the deferred payload, read
  its `frame_paths`, and commit via
  `commit_shot_vision(clip_id, shots=[{shot_index, ...groups...}],
  vision_token)`. Deep fields land as `vision_deep_v1` provenance rows;
  human corrections always survive. Shots with no sampled frames on disk get
  1–2 frames re-extracted via ffmpeg (read-only on source media).
`vision_pending_sweep(expire?, max_age_days?, reoffer?)` lists clips stuck
in `pending_host_analysis`; `reoffer=true` returns each clip's stored
deferred payload to finish the run, `expire=true` stamps them
`expired_host_analysis` so pendings never linger silently.

**DB-canonical analysis store (v2.41.0+).** The per-project SQLite DB
(`_soul/timeline_brain.sqlite`, schema v9+) is the source of truth for clip
analysis; `analysis.json` is a derived export written in lockstep. Analysis
runs write rows first (clips, shots, per-field subjective provenance,
transcript segments, sampled frames, QC observations) and then export the
JSON. Human corrections recorded via `update_clip_field` / `update_shot_field`
live as row-level provenance and always survive re-analysis. Readers
(panel API, exports) load DB-first and fall back to `analysis.json` for
reports that predate v9. `db_status` reports schema version + row counts;
`db_ingest` migrates an existing project's JSON reports (and
`corrections.json` sidecars) into the DB — run it once on older analysis
roots.
The tool never installs
dependencies and validates that outputs stay under
`davinci-resolve-mcp-analysis` project roots rather than beside source media.
Executed Resolve-target analysis defaults to running, persisting inspectable
artifacts, and publishing metadata plus Media Pool clip markers. Use
`dry_run=true`, `publish_metadata=false`, `timed_markers=no`, or
`session_only=true` with `keep_artifacts=false` to disable those defaults for a
run. Persisted analysis refreshes the local SQLite search index automatically unless
`auto_build_index=false` is set; `build_index` remains the manual rebuild action
for existing reports. `quick` uses ffprobe metadata; `standard` adds ffmpeg
read-through checks,
cut-boundary analysis from full-stream scene detection, flash-frame candidates,
motion/variance scoring, analysis keyframes, and sidecar reports.
`depth` controls which layers run; a separate `sampling_mode` controls how many
frames each clip gets for visual analysis (and thus token cost): `fixed`
(Economy, flat content-blind frames), `per_minute` (Balanced, frames scale with
duration), `adaptive_capped` (Thorough, content-aware bounded to
`[frame_floor, frame_ceiling]` — recommended/default), or `adaptive` (Thorough
uncapped). When no default is saved, the first analyze returns
`confirmation_required` with a `sampling_mode_prompt`; choosing a mode saves it
as the default. Pass `sampling_mode` per call for a one-off. The mode owns frame
count — `analysis_caps.frames_per_clip` is a safety ceiling above it, not the
primary dial.
By default, planning checks the active project's analysis root and bounded
related project-version roots for existing reports, then marks matching clips
`skip_execution=true` when those reports already contain the requested
technical, motion, transcription, and vision layers.
Resolve clip records also carry the published third-party
`davinci_resolve_mcp.analysis_report_path` when metadata writeback has run; use
that provenance as a first-class reuse hint even if the report lives under a
previous project-version analysis root.
The planner also maintains an `analysis_registry.json` under the analysis base
root. This registry indexes report paths by source path, clip id, media id, and
signature so project renames and versioned Resolve projects can still find prior
work quickly.
Reports include cache signatures with source stat, depth, frame budget, prompt
hash, and requested modalities. Use `force_refresh=true` for a fresh read,
`max_report_age_days` for freshness limits, and `reuse_policy="fresh"` when
unsigned older reports should not be reused. Pass `reuse_existing=false` only
when the user explicitly wants to ignore memory; pass
`search_related_project_roots=false` only for intentionally isolated runs.
If Resolve metadata shows prior MCP analysis but the planner cannot validate a
matching report, execution returns `status="reuse_blocked"` instead of silently
reanalyzing. Treat that as a project-memory integrity warning; restore the
report or pass `force_refresh=true` only when the user explicitly wants fresh
analysis.
Transcription, visual analysis, metadata writeback, and Media Pool marker
writeback are default-on. Vision uses
`vision.provider="host_chat_paths"`: analyze actions extract representative
frames to disk under the project analysis root and return a deferred payload
containing absolute `frame_paths`, a `shot_table` mapping each detected shot
range to its in-shot `frame_indices`, the JSON schema, and a `commit_action`.
The host chat must read those frames as local images, produce JSON per the
schema (including one `shot_descriptions` entry per `shot_index` in the
`shot_table`, grounded only in the frames listed for that shot), and call
`media_analysis(action="commit_vision", params={clip_id, visual,
vision_token})` per clip to merge the visual report, rebuild Media Pool clip
markers, and publish vision-dependent metadata to Resolve. Each Resolve shot
marker inherits its description from `shot_descriptions[shot_index]`; missing
entries fall back to an in-range `analysis_keyframe` and finally to a
clip-summary-tagged fallback — never to a neighbour shot's description. The manifest exposes
`vision_pending=True` and `pending_action` so callers know what is incomplete.
Pass `include_visuals=false`, `include_transcription=false`,
`publish_metadata=false`, or `timed_markers=no` to opt out. Agents must not add
those opt-out flags preemptively; use them only when requested or when a target
boundary requires it. Standard/deep runs prioritize first/last usable frames
plus before/after cut-boundary frames as the sampled set. Skipping
`commit_vision` leaves the run in `pending_host_vision_analysis` — that is a
failure mode to surface, not a silent downgrade. The local mock providers are
for tests and do not send frames off-machine.

When creating timelines through `media_pool`, use `if_exists="reuse"` for
idempotent reruns, `if_exists="version"` for deliberate alternate cuts, and
`if_exists="fail"` when duplicate names indicate a workflow error.
Use `detect_sync_events` before multicam setup, deliverable QC, or single-camera
sync review when the user needs likely 2-pop or slate-clap locations. It reads
source audio through FFmpeg/FFprobe only, returns advisory frames/timecodes and
per-file `record_offset` suggestions, and never installs FFmpeg automatically.
It also returns marker suggestions; `add_sync_event_markers` remains an explicit
marker-write action for standalone sync detections.
Use `publish_clip_metadata` when the user wants analysis to become searchable
inside Resolve. It analyzes or reuses reports, proposes field-specific merges
for `Description`, `Comments`, `Keywords`, `People`, and optional slate-derived
fields, stores provenance in third-party metadata, and writes metadata plus
source-time markers by default for executed Resolve-target analysis. Disable a
write run with `dry_run=true`, `publish_metadata=false`, or `timed_markers=no`.
`review_timeline_markers` creates a labeled
Resolve-rendered marker contact sheet plus JSON sidecar; with
`vision.enabled=true` it returns a host_chat_paths review payload (image_path +
prompt) so the host chat can read the sheet and answer inline — no commit step
required for marker review.

Before calling `analyze_*`, prefer `summarize` and `get_report` to discover
existing reports for the active project. If reports exist, use them as the
working memory for edit decisions and only request fresh analysis when a missing
layer changes the decision. If a user is
making story or audio-spine decisions and transcription is available but disabled,
tell them that transcript analysis may materially improve the edit instead of
silently skipping it. Resolve-native transcription changes project state; use it
only when that mutation is intentional.

---

### Timelines

**`edit_engine`** — Evidence-driven edit loops (v2.45.0+): selects assembly,
tighten, swap.

Every loop is plan → confirm → execute. plan_* actions are dry-run by
construction: they query the DB-canonical analysis store and return a
per-decision rationale plus a stored `plan_id` (plans persist under
`memory/edit_plans/` with a content fingerprint, so a stale plan cannot run
against a changed project). execute_* actions require a `confirm_token`, run
under the version-on-mutate hook, and return before/after duration and
clip-count readback plus `brain_edits` rationale rows.

- `plan_selects(min_select_potential?, max_duration_seconds?, max_shots?,
  timeline_name?, analysis_root?)` — ranks shots by deep-tier
  `editorial.select_potential` / best moments (clip-level fallback for
  standard-analyzed clips), story-spine order.
  `execute_selects(plan_id)` creates a NEW selects timeline from the plan's
  per-shot source ranges — additive; nothing existing is touched.
- `plan_tighten(timeline_name?, target_ratio?, min_pause_seconds?,
  handle_seconds?, include_audio?)` — dead-air lifts from transcript-gap
  evidence for each timeline item (items without transcripts are reported in
  `skipped`, never silently trimmed). `execute_tighten(plan_id)` assembles a
  tightened VARIANT timeline from the plan's keep ranges — true partial
  trims; the original timeline is never mutated. v2.52.0+: kept ranges mirror
  onto each item's linked audio track(s) so the variant is audible (a
  speech-driven cut was previously silent — #67); pass
  `include_audio=false` for a video-only assembly, and the
  `execute_tighten` readback carries an `audio_accounting` block.
- `plan_silence_ripple(timeline_name?, track_index?, threshold_db?,
  min_strip_frames?, pre_head_frames?, post_tail_frames?, include_audio?)` —
  waveform silence strips via ffmpeg `silencedetect`, mirroring Resolve's
  *Clip → Audio Operations → Ripple Delete Silence* (defaults: −30 dB,
  10-frame minimum strip, 2 pre-head, 4 post-tail frames — guard bands that
  keep the cut off the outgoing word's decay and the incoming word's attack).
  Items without
  readable file paths ride along whole (reported in `skipped`), so the
  variant never silently loses content. `execute_silence_ripple(plan_id)`
  assembles a tightened VARIANT timeline from keep ranges — same safety model
  as `execute_tighten` (original untouched, confirm token, audio mirroring).
- `plan_dead_space_markers(timeline_name?, track_index?, threshold_db?,
  tightness?, min_strip_frames?, pre_head_frames?, post_tail_frames?)` —
  **review before you cut.** Finds dead space with the *same* calibrated gate as
  `plan_silence_ripple` but proposes Resolve **markers** instead of an edit, so
  an editor can look at every gap, delete the markers they disagree with, and
  only then tighten. Reach for this whenever the ask is "show me the gaps
  first" — it is the review gate, and without it an agent will invent its own
  detection and mark the wrong spots. Red = confident; **Yellow = the gate only
  just cleared its separation floor, so speech and room are close together and
  the call deserves a second look.** Nothing is written: pair the returned
  marker specs with `timeline_markers`. Items in `skipped` were *not* analyzed
  and are explicitly **not** certified clean.
  `tightness` (`generous` default | `balanced` | `tight`) scales the guard bands
  and the minimum gap length — see below.
- `plan_report(plan_id, max_detail_rows?)` — **render any plan as a reviewable
  Markdown report.** A 340-entry `keep_ranges` array is not reviewable, and the
  rational response to a machine you cannot audit is to re-check it by hand,
  which is the cost the tool was meant to remove. The report states: what would
  change (in **timecode**, with a reason per cut), what was **deliberately left
  alone** (invisible in the output, and the half people distrust most), what
  could **not** be verified (never folded into "fine"), and what **needs a
  human**. Returns both `report_markdown` and a one-line `summary` for chat.
  Every plan kind renders, including ones this renderer does not know about.
- `rank_takes(clip_refs[], script?)` — rank several clips of the same material by
  **measurable fluency**: filler density, stammered restarts, longest clean run,
  and (with a `script`) how much of the intended line got said. **It ranks
  fluency, not quality, and says so in every response.** Performance is most of
  what makes a take right and none of it is measurable here — the take that
  plays is regularly the least fluent one, because the hesitation is often the
  acting. Use it to find the clean safety take or skip the warm-ups, never to
  choose the read. Clips without transcripts are listed in `unavailable`
  (**absent from the ranking, not last in it**), and takes too short to score
  are flagged rather than dropped.
- `plan_beat_cuts(clip_ref | media_path, mode?, beats_per_bar?, bars_per_phrase?,
  beat_offset?, min_shot_seconds?, timeline_fps?)` — **cut points from the music's
  own pulse**, for footage with no speech. The speech tools find edit points in
  words and pauses; music has neither, and pointing a silence gate at it makes
  engine noise read as content and quiet read as dead space. `mode`: `beat` (every
  beat — relentless), `bar` (downbeats), **`phrase` (default)** — music resolves at
  phrase boundaries, which is what makes a cut feel inevitable rather than merely
  synchronised. Frame-snapped. **Downbeats are inferred, not detected** (the first
  beat is assumed to start a bar) — a track with a pickup needs `beat_offset`, and
  that is the first thing to check if cuts feel consistently one beat early.
  Reports its own tracking confidence. Requires the optional `librosa` extra
  (`pip install librosa`, ISC) and **honest-refuses without it** rather than
  inventing a tempo. Returns cut POINTS, not an assembly.
- `plan_prebalance(timeline_name?, track_index?, max_items?)` — **neutral technical
  pre-balance**, the assistant colorist's highest-leverage pass. Measures black and
  white points per channel off a mid-shot frame, groups by setup, picks a hero, and
  proposes one bypassable **`ASST: Balance`** node per clip. Black balance on the
  parade first, then white point. **Midtones are deliberately left warm** — skin
  belongs near 11 o'clock on the vectorscope, and neutralizing midtones is the
  fastest way to make everyone grey. Curves, vignettes, saturation, qualifiers and
  windows are **refused in code**, not merely discouraged. Clipped highlights and
  crushed shadows are flagged as `ASST: TECH/CREATIVE` markers, never silently
  fixed. It has scopes and no eyes: numeric balance is defensible, look development
  is not, and it cannot know the dim shot was dim on purpose.
- `rule_of_six_audit(timeline_name?, track_index?)` — audits a timeline against
  the **Rule of Six** — the classical weighted cut criteria — and is loud about
  what it cannot see. Those weights
  are inverted against measurability: **everything computable is the bottom 26%**.
  So **emotion (51%) and story (23%) appear in every response as `NOT_ASSESSED`
  and cannot be suppressed**, criteria this build does not compute report
  `NOT_IMPLEMENTED` (never a pass), and coverage is stated outright — *"1 of 6
  criteria assessed, covering 10% of the decision."* **There is deliberately no
  composite score**; averaging 26% into one number implies it describes the cut.
  Findings order by scope ("movie first, scene second, moment third")
  then by criterion weight — never by volume, so a rhythm problem (10%) always
  outranks a screen-geography one (5%). Rhythm is implemented: metronomic runs
  are flagged, and a pattern break landing on a marker is reported as **craft,
  not a finding** — the break is where meaning lives. Cuts/min is compared to
  the 14–16 commonly observed in dialogue, explicitly **descriptive not
  prescriptive**.
- `split_edit_audit(timeline_name?, track_index?)` — **sound leads picture**.
  The ear is faster than the eye, so the classical advice is to treat the cut as
  a sound event first. Classifies every join: **L-cut** (audio edit later — outgoing
  sound lingers), **J-cut** (audio earlier — incoming sound pulls forward), or
  straight. A picture cut with no nearby audio edit is reported as **unpaired,
  not straight** — sound running continuously across a join is a *stronger* form
  of sound carrying picture. Flags a timeline where every join is straight: that
  is where the NLE puts audio edits by default, and a dialogue sequence with no
  split edits anywhere is usually one nobody has listened to yet. **No correct
  ratio is suggested and none exists** — a montage, a two-hander and an
  interview all want different distributions.
- `sound_density_audit(track_media, stream_limit?, duration_seconds?)` — the
  **two-and-a-half rule**: an audience follows roughly 2.5 simultaneous sound
  streams before the rest becomes texture. The distinction that makes this usable
  is **competing vs. layered** — a music bed under dialogue is one stream plus
  texture, not two competitors, and a version that counted active tracks would
  flag every mixed timeline ever made. A stream within 12 dB of the loudest
  counts as competing; further under counts as a bed. **2.5 is a long-standing
  observation in sound editing, not a measured constant** — it is a parameter and its provenance
  travels with every result. Pass rendered stems for a true reading; source clips
  give a reading of the sources, and the response says which it got.
- `setup_sheet(timeline_name?, track_index?)` — **the wall of stills**: one
  representative frame per *setup*, not per shot, so twenty images stand for the
  whole film instead of two hundred reproducing the timeline at higher
  resolution. Frame taken from the middle of that setup's longest usage (heads
  and tails catch fades, slates and handles); ordered by **first appearance** so
  the sheet reads in the direction the film does. Grouping is reel-name-else-
  folder — a stated proxy for lighting setup, which Resolve does not expose.
- `first_impression(op=start|record|lock|get|list|diff, …)` — the editor is the
  only person who gets to be a first-time audience, and that perception is
  destroyed by the second viewing. Captures timestamped reactions during a first
  pass and then **seals them**. `record` on a locked log raises; **there is
  deliberately no unlock** — an impression that can be revised later is
  worthless, because by then what changed is the viewer, not the film. Free text,
  **no schema and no sentiment scoring** — the words are the artifact. `diff`
  reports whether a later pass **revisited** each reaction and explicitly refuses
  to claim anything was *fixed*.
- `plan_reference_match(reference_media, reference_at_seconds?, timeline_name?, max_items?)`
  — match clips to a **graded reference still**, the way a colorist actually
  communicates ("make it look like this one"). Reuses `prebalance.validate_plan`
  rather than reimplementing the guardrails, so this path cannot permit what the
  neutral path forbids. **END POINTS ONLY, stated in every response** — it puts
  a shot in the reference's tonal neighbourhood and does **not** transfer the
  reference's grade; curves, vignettes and secondaries stay where they are.
  Matching across dissimilar subject matter (night exterior vs white cyc) is
  reported as **low confidence** rather than delivered with a straight face.
- `plan_string_out(shots, order?)` — assembly for footage that does not talk.
  Speechless material is cut from **shots and motion**, not silence: point a
  speech gate at motorsport and engine noise reads as content while a quiet
  straight reads as dead space. `order`: `chronological` (default) or
  `activity`. **Unmeasured motion is never treated as static**, a locked-off
  shot is described rather than penalised, and ranking by movement is a
  measurement not an edit — the most important shot may rank last. Returns a
  string-out, never a cut.
- `propose_structure(topics)` — **no-script mode**. Orders topics by coverage,
  which measures what was *shot* and not what matters, and says so.
  `requires_approval` is always true: a structure inferred from clustering is a
  hypothesis about what the piece is, and the decision least safe to take
  silently.
- `plan_broll(beats, candidates, allow_reuse?)` — place B-roll against A-roll
  beats. **Placement only: relevance is whatever your matcher said and is never
  re-scored here**, because whether a shot illustrates a line is not something
  this can see. Cutaways sit *inside* a beat rather than straddling one; a beat
  marked `protected` is never covered; an explicit `beat_index` is honoured
  there or not at all, never silently moved somewhere it fits better.
- `plan_turnover(destinations, contents, version?, handle_frames?)` — validate
  **sound / VFX / colour turnover manifests** against spec. Per-destination
  handle floors (sound 48 frames, picture 8 — crossfades and room tone reach
  past the picture cut), and a **timecode-burned picture reference is required
  in all three**, its absence a blocker: without one the receiving editor cannot
  verify anything against your intent. Includes the burn-in spec (both source
  *and* record timecode). **Manifests, not exports** — an export that runs
  perfectly and omits the textless is still a failed turnover, and rendering
  needs a live Resolve.
- `journal(op=append|read|known_issues|ingest_log|session_prep|handoff|status|
  picture_lock|check_lock, …)` — the paperwork every craft role keeps and every
  tool skips. **Append-only:** resolving an issue appends a resolution and never
  deletes the issue, so the one nobody got round to is still there when someone
  asks why a shot shipped soft. `session_prep` carries open issues plus the value
  figures (prep hours, hours saved, rate) because the prep has to justify itself
  in the next budget round. `handoff` prints missing fields as **NOT STATED**
  rather than omitting them — a handoff that silently drops the frame rate reads
  as complete and the gap surfaces after work has started. `picture_lock` records
  a fingerprint of the cut and `check_lock` reports drift; the fingerprint hashes
  the **edit points**, not just counts and totals, so shots redistributed inside
  an unchanged runtime — exactly what a trim pass produces — still trip it.
- **All audits accept `include_report=true`** for a Markdown rendering (what
  changed, what was deliberately left alone, what could not be verified, what
  needs a human). Off by default because rendering costs tokens on every call;
  every audit advertises it in `report_available`.
- `conform_lint(timeline_name?, track_index?)` — **the online editor's checklist,
  run before turnover** instead of discovered after picture lock in someone else's
  suite. Blockers: frame-rate mismatch, offline media, two sources claiming one
  source timecode (misnamed cards — the most common reason a relink fails).
  Warnings: items buried under opaque layers, track overlaps, missing reel names,
  and effects that will not survive interchange (Premiere's *Scale to Frame Size*
  is the classic — its sizing data does not reach Resolve at all). It reports, it
  does not fix, and **checks that could not run for want of data are listed in
  `not_checked`** rather than counted as passes.
- Plans now carry a **`handle_report`**: keep ranges that leave too little source
  media at a join for a dissolve, a slip or an audio crossfade. Picture floor 8
  frames, audio 48 — audio is far larger because crossfades and room tone reach
  past the picture cut. It reports rather than blocks (cutting to the head of a
  clip is often unavoidable), but **an unverified handle is never reported as a
  passing one**.
- `plan_swap(timeline_start_frame | item_name, kind="visual"|"text",
  limit?)` — alternates for one timeline item via the similarity index,
  filtered to shots long enough to fill the slot exactly.
  `execute_swap(plan_id, alternate_index)` replaces the item in place
  (lift + positioned append at the same record frame) on the
  version-archived timeline. v2.48.0+: the lift is scoped to the target's
  video track plus its linked audio tracks (GetLinkedItems with a
  media-id fallback), and `readback` carries per-track-type
  `track_counts` plus an `audio_accounting` block so swap symmetry is
  verifiable. `execute_tighten` readback gains `structural_diff` (source
  vs variant, via the same engine as `diff_timelines`) — compact by
  default (counts + a small sample; full per-item diff persisted in the
  plan record via `get_plan`, or inline with `include_details=true`);
  `execute_selects` readback gains a `usage_summary`.
- `list_plans(limit?)` / `get_plan(plan_id)`.

The engine needs the analysis substrate: analyzed clips in the DB (run
`db_ingest` on older roots), transcripts for tighten, and visual embeddings
(`build_embeddings(kinds=['visual'])`) for swap.

Plans are reviewable in the control panel (Media → Edit Plans, v2.47.0+):
decisions/lifts/alternates with thumbnails and rationale, deep links to shot
pages, and a copyable per-kind execute prompt. The panel never executes —
when the user says they reviewed a plan there, execution still comes back
through chat with the confirm-token gate.

**`timeline_versioning`** — Version-on-mutate, archive, rollback, brain-edit history (C6).

Every destructive timeline op (compound, captions, ripple delete, gap close,
retime, marker batch, track add/delete, take swaps, color grade, etc.) auto-
archives the working timeline to the `Archive` bin under an `analysis_run_id`
before the mutation runs. This tool surfaces and controls that history.

Key actions:
- `begin_run(label?, initiator?, analysis_run_id?)` — open a multi-step run.
  Subsequent destructive calls auto-thread this run's ID, so a brain
  operation that touches 5 clips creates ONE archive + 5 logged edits
  instead of 5 separate archives.
- `end_run(analysis_run_id?)` — close the run; aggregates brain_edits into
  per-metric rollup in `analysis_runs.summary_json`.
- `list_runs(limit?)` — recent runs newest first with their summaries.
- `archive_current(reason?, analysis_run_id?)` — manual checkpoint of the
  current timeline. Idempotent within an `analysis_run_id`. Also captures a
  structural snapshot (every clip's placement, written to `timeline_clip_usage`)
  and a thumbnail (when the Color page has a current clip).
- `list_versions(timeline_name)` — version chain, oldest first. Each row
  includes `archived_timeline_name`, `created_at`, `analysis_run_id`,
  `initiator`, `thumbnail_path`, and `drt_export_path` (set when the version
  was retention-collapsed to disk).
- `diff_versions(timeline_name, from_version, to_version)` — structural diff
  between two snapshots: `{added, removed, moved, trimmed, summary}`. `trimmed`
  lists clips kept in place but re-trimmed (carries `out_frame_before`); `summary`
  has per-bucket counts plus `before_clip_count`/`after_clip_count`. Clips are
  keyed by media_pool_item_id and timeline position.
- `diff_timelines(from_timeline, to_timeline)` (v2.48.0+) — the same
  structural diff between two LIVE timelines by NAME, read-only, no archived
  snapshots needed. Built for edit-engine variants (tighten/selects produce
  new-name timelines with no shared version chain). For unrelated timelines
  everything reports as added/removed.
- `get_history(timeline_name?, analysis_run_id?, limit?)` — brain-edit rows
  with `edit_type`, `target_metric`, `before_value`, `after_value`, `delta`,
  `rationale`, and `initiator`. Filter by timeline or run; defaults to 50.
- `media_pool_changes(analysis_run_id?, media_pool_action?, limit?)` —
  destructive media-pool history (deletes, replaces, relinks) from the
  `media_pool_changes` table. Separate from brain_edits because the
  addressable entity is a media_pool_item, not a timeline.
- `rollback(timeline_name, version, analysis_run_id?)` — archive current first,
  then duplicate the archived version back as a new `<name>_rolled_back_<HHMMSS>`.
- `prune(timeline_name, keep_n=10)` — collapse old versions to `.drt` exports
  under `<project>/_soul/timeline_versions/<slug>/` and remove them from the
  bin. DB row preserved with `drt_export_path` populated for later rollback.
- `registry()` — cross-project brain-edits registry that lives at the analysis
  base root (one level above each project_root). Mirrors `analysis_registry.json`.

**Strict mode** — `timeline.delete_timelines`, `timeline.delete_track`, and
`timeline.delete_clips(ripple=True)` REFUSE to run when the pre-mutation
archive can't be created. Pass `strict=true` on any destructive op to opt in.
This prevents catastrophic ops from proceeding when versioning is broken.

**Action filtering** — `timeline_item.set_property(key='Notes')` and
`timeline.set_clip_property(key='Notes'|'Comments')` bypass versioning because
free-text metadata isn't worth archiving. See `NO_ARCHIVE_ON_KEYS` in
`src/utils/destructive_hook.py` to add more.

**Preferences** — `timeline_versioning_auto_save_after_archive` (default false)
triggers `project.SaveProject()` after every archive so Resolve crashes don't
lose history. Configure via the `setup` tool's preferences.

### Analysis Caps

`media_analysis` honors a project-wide caps preset that controls 7 dimensions
of analysis cost: response payload size, frames per clip, vision tokens per
clip / per job / per day, wall-clock seconds per call, and the maximum frame
image dimension before upload. Four named presets, plus per-field overrides.

| Dimension                     | minimal | standard | generous  | unlimited |
|------------------------------:|--------:|---------:|----------:|----------:|
| response_chars                | 5,000   | 25,000   | 100,000   | none      |
| vision_tokens_per_clip        | 5,000   | 25,000   | 100,000   | none      |
| frames_per_clip               | 4       | 8        | 24        | none      |
| vision_tokens_per_job         | 50,000  | 250,000  | 1,000,000 | none      |
| vision_tokens_per_day         | 100,000 | 500,000  | 2,000,000 | none      |
| wall_clock_seconds_per_call   | 30      | 90       | 300       | none      |
| max_frame_dim_pixels          | 512     | 768      | 1280      | none      |

Default preset: `standard`. Set via `media_analysis(action="set_caps_preset",
preset=…, overrides={...})` or the dashboard's **Preferences → Analysis Caps**
panel. Inspect via `media_analysis(action="get_caps")` which returns the
effective values + a usage rollup (clip / job / day) with percent-consumed.
`media_analysis(action="get_usage", scope="day"|"job"|"clip")` returns raw
counts for one scope. Usage is tracked in
`<project>/_soul/timeline_brain.sqlite` (`analysis_token_usage` table).

Resolve 21's local AI ops (audio classification, IntelliSearch, slate,
motion-deblur, speech generation) run on Resolve's own GPU/AI engine and do NOT
spend the Claude analysis token budget — they are tracked separately in the
`resolve_ai_op_usage` table. Inspect with
`media_analysis(action="get_resolve_ai_usage", session_only?, op?, limit?)` →
`{summary, recent}` (invocation counts, wall-clock, and files/bytes created by
`remove_motion_blur` / `generate_speech`). The control panel shows the same as a
read-only "Resolve 21 AI ops" card.

The two media-creating ops also have **soft governance tiers**
(`off`|`lenient`|`standard`|`strict`, default `standard`) capping per-session
deblur/speech runs, bytes, and render time. It is advisory — the confirm dialog
warns when near/over the tier but never blocks (the ops are confirm-gated).
Inspect/set with `media_analysis(action="get_ai_governance")` and
`media_analysis(action="set_ai_governance", preset=…, mode=…, overrides={...})`.
Governance `mode` is `advisory` by default (preview warnings only); `enforce`
blocks an over-tier run with `GOVERNANCE_BLOCKED` until the tier is raised, the
mode is relaxed, or the op is re-called with `override_governance=true`. Ledger
rows, brain edits, and timeline versions record the acting instance
(`stdio` / `network-sse` / `network-http` / `control-panel` / `batch-cli` + pid)
in an `actor` field; the AI
Console's Governance section offers a tier picker + consumption gauges.

The caps layer:
- Slices `frame_paths` to `frames_per_clip` before the host LLM sees them.
- Downscales each sampled frame in place to `max_frame_dim_pixels` (Pillow;
  degrades silently to original-resolution upload if not installed).
- Trims the analysis response payload to `response_chars`, dropping the
  largest list/string fields first and marking the trim under `_trimmed`.
- Records actual token usage from the host's `commit_vision` payload's
  optional `usage: {vision_tokens, ...}` block. Hosts that don't report
  tokens still get `frames_uploaded` recorded.

Wall-clock timeout + cumulative-budget refusal are implemented in
`src/utils/analysis_caps.py` and ready to hook at additional call sites in
the analysis pipeline; the initial integration is at frame sampling +
response construction + commit_vision usage recording.

**Declared edits** — when the brain (or an agent acting deliberately) wants to
measure an edit, pass `metric`, `direction`, and `rationale` in the params of
the destructive call. The hook captures `before_value` and `after_value` from
the live timeline (using the metric vocabulary in `brain_edits.py`) and writes
them to the `brain_edits` row. Without these, the edit is still logged but with
null metric — gives history without requiring deliberate intent.

Supported metrics: `duration_seconds`, `avg_performance_score`, `clip_count`,
`gap_count`, `total_gap_seconds`, `redundancy_score`.

**`timeline`** — Timeline operations: tracks, clips, import/export, generators.

Key actions:
- `list` — all timelines in the project
- `get_current` — current timeline info
- `set_current(index)` — switch timeline by 1-based index
- `get_track_count(track_type)` — track_type: `"video"`, `"audio"`, `"subtitle"`
- `get_transcript(with_timecodes?)` — read the subtitle track(s) as transcript
  text `{text, cue_count, has_subtitles, cues}`
- `propose_cuts(cues?, long_pause_frames?)` — DRY-RUN: mechanically detect
  candidate cuts (fillers, long pauses, repeats) from the transcript; proposes only
- `apply_cuts(cuts, dry_run?, confirm_token?)` — apply a CutList as lift/ripple
  deletes. DRY-RUN by default; applying is destructive (confirm-token gated, a
  timeline version is archived first). Cuts apply latest-first
- `add_track(track_type, sub_type?)` / `delete_track(track_type, index)`
- `get_items(track_type, index)` — items on a track
- `clip_where(track_type?, track_index?, name_contains?, duration_lt?, duration_gt?)` —
  (v2.28.0+) return clips on the current timeline matching named filters (AND),
  instead of walking tracks by hand. Filters may be passed inline or as a
  `filters` dict; a mistyped filter name is rejected rather than silently
  matching everything. Returns `{clips, match_count, total_clips}`.
- `delete_clips(clip_ids, ripple?)` — IDs are unique IDs from `get_items`.
  Two verified quirks (see `api_truth`): the call can return `success: false`
  on the first attempt with valid IDs — re-list and retry once before failing;
  and deleting a video item does NOT delete its linked audio — pass the linked
  audio item IDs explicitly, then `detect_gaps_overlaps` across both track
  types.
- `duplicate_clips(clip_ids?, selected?, target_track_index?, track_offset?, placement?, record_frame?, record_frame_offset?, copy_properties?, include_linked?)` —
  duplicate existing video timeline items by re-appending the same Media Pool
  item with the same source trim; `selected=True` uses Resolve's selected/current
  item when available, `placement` supports `"same_time"`, `"offset"`,
  `"at_playhead"`, `"track_above"`, `"after_source"`, and `"next_gap"`, and
  `include_linked=True` duplicates linked audio and restores link state.
  `copy_properties` can copy `transform`, `crop`, `composite`, `audio`,
  `retime`, `dynamic_zoom`, `scaling`, `stabilization`, `clip_color`,
  `markers`, `flags`, `enabled`, `cache`, `voice_isolation`, `fusion`,
  `grades`, `takes`, and `keyframes`; `transitions` is accepted but reported
  unsupported because Resolve's public scripting API does not expose transition
  cloning. `copy_keyframes=True` adds the `keyframes` group.
- `copy_clips(...)` / `move_clips(...)` — same safe append path; `move_clips`
  deletes only sources whose duplicate was VERIFIED live on the timeline
  (AppendToTimeline can return null-id items — e.g. into an occupied span — and
  unverified sources are kept with a warning; see api_truth
  'AppendToTimeline null-id'). NEVER use `move_clips` to open a gap for an
  insert; that is `ripple_insert`'s job.
- `ripple_insert(clip_infos, record_frame|record_timecode, record_frame_mode?,
  dry_run?, confirm_token?)` — insert media-pool source ranges at a record point
  and shift ALL later video/audio items right. DRY-RUN by default (full plan
  with straddler/blocker detection); executing is confirm-token gated and
  archives the timeline first. Shifted items are re-created from pool media
  with transform/crop/composite/retime re-applied; grades, keyframes,
  transitions, and link state on shifted items are NOT preserved (the archive
  keeps them). Refuses mid-item insert points, non-pool items in the tail
  (titles/generators/Fusion comps), subtitle shifts, and locked tracks.
- `copy_range` / `duplicate_range` — copy exact video/audio source segments
  from `start_frame`/`end_frame` or mark in/out to `record_frame`
- `overwrite_range` — delete whole destination overlaps, then copy the exact
  range segment
- `lift_range` — delete whole items in a range; partial overlaps require
  `allow_partial_item_delete=True` because Resolve does not expose a safe
  partial lift primitive here
- `story_spine_report` — read markers, source ranges, and audio/video structure
  into an editor-facing beat report
- `create_variant_from_ranges(name, ranges, markers?, cdl?, dry_run?)` — create
  a guarded timeline variant from declarative source ranges, optional markers,
  transforms, and CDL. Each range takes `track_type?` and a 1-based
  `track_index?` (default 1), so multicam angles can be rebuilt onto V2/V3
  rather than collapsing onto V1; missing tracks are added
- `bulk_set_item_properties(ops, dry_run?, readback?)` — apply transforms,
  crop/composite/audio/property groups to many timeline items in one call. An op
  may carry `clip_color` and/or `enabled` with nothing else, which is the triage
  shape: paint a whole selection in one round trip. A colour is verified by
  readback, so a name outside the Edit-page palette and the generator/title case
  that returns True and drops the colour both fail the op instead of passing
- `apply_look_to_items(target_ids, cdl?|copy_from_item_id?, dry_run?)` — apply a
  normalized CDL and/or copy a source grade to multiple video items
- `thumbnail_contact_sheet` / `marker_thumbnail_review` — sample Resolve
  thumbnails under the project analysis root. These are CLIP thumbnails, so the
  sheet is effectively one image per clip, not per sampled frame — a shot
  inventory rather than frame evidence. Resolve only serves them on the Color
  page and only while it is frontmost; the tool switches page automatically and
  restores the previous one. Expect a page flash in the GUI,
  and note that landing on Color can kick off cache/render work for the current
  clip — on a large timeline the switch is not free.
  NOT WYSIWYG for Fusion: thumbnails do not reflect Fusion composition output
  (a warp demo read as identical before/after from a contact sheet,
  2026-08-19). Prove Fusion/grade claims with `gallery_stills grab_and_export`
  or an extracted RENDERED frame, never a thumbnail
- `edit_kernel_capabilities` — report supported, partially supported, and
  unsupported timeline edit kernel behavior
- `probe_edit_kernel_item(clip_ids? selected? timeline_item?)` — read-only
  capability/property probe for timeline items, including available item
  methods, `GetProperty()` values, known property keys, keyframe counts, and
  linked item summaries
- `title_property_scan(clip_id|timeline_item_id|timeline_item)` — inspect
  undocumented Edit-page title/generator `TimelineItem.GetProperty()` keys
- `set_title_text(clip_id|..., text, property_key?, as_styled_xml?, try_plain_first?, try_heuristic_keys?, readback?)`
  / `bulk_set_title_text(ops, ...)` — update title text via explicit or scanned
  keys when the current Resolve build accepts the `SetProperty()` write
- `export(path, type, subtype?)` — type: `"AAF"`, `"EDL"`, `"FCPXML"`, `"DRT"`, etc.
- `insert_generator(name)`, `insert_title(name)`, `insert_fusion_title(name)`
- `get_mark_in_out`, `set_mark_in_out(mark_in, mark_out, type?)`
- `duplicate(name?)` — duplicate the current timeline
- `get_voice_isolation_state(track_index)` / `set_voice_isolation_state`
- `extract_source_frame_ranges(handles?, gap_max?, skip_extensions?)` — return
  inclusive source frame ranges for current-timeline video clips, with fixed
  handles or gap-only auto handles when `handles=0`

Timeline Conform / Interchange kernel actions (v2.13.0+) add live-tested
structure, interchange, comparison, missing-media, and relink-planning helpers:

- `conform_capabilities`
- `probe_timeline_structure(track_types?, include_markers?, include_clip_properties?)`
- `detect_gaps_overlaps(track_types?, min_gap?)`
- `source_range_report(handles?, merge?)`
- `export_timeline_checked(path, format?|type?, subtype?, require_temp_path?, dry_run?)`
- `import_timeline_checked(path, options?, timeline_name?, import_source_clips?, require_temp_path?, dry_run?)`
- `compare_timelines(right_timeline_id?|right_timeline_index?|left_snapshot?, right_snapshot?)`
- `probe_interchange_roundtrip(format?, output_dir?, cleanup_imported?)`
- `detect_missing_media(sanitized?|sanitize_paths?, omit_raw_paths?)`
- `build_relink_plan(search_roots, max_depth?, max_seconds?, max_files_scanned?, skip_search_when_volume_missing?, sanitized?)`
- `conform_boundary_report`

For offline media, prefer the sanitized readback first:
`timeline(action="detect_missing_media", params={"sanitized": true})`. The
response includes a `diagnosis` block with deduplicated Media Pool items,
missing volume roots, sample basenames, and a recommended next step. If a source
volume such as a camera card is not mounted, `build_relink_plan` skips broad
search by default and reports `skip_reason="missing_source_volume_not_mounted"`;
mount the volume or pass `skip_search_when_volume_missing=false` only when a
bounded scan of approved roots is intentional.

Audio / Fairlight kernel actions (v2.14.0+) add live-tested audio state,
mapping, voice-isolation, sync, transcription, subtitle, and Fairlight boundary
helpers:

- `audio_capabilities`
- `probe_audio_track(track_index?)`
- `probe_audio_item(track_type?, track_index?, item_index?)`
- `safe_set_audio_properties(properties, restore?, dry_run?, track_type?, track_index?, item_index?)`
- `audio_mix_capability_report(...)`
- `voice_isolation_capabilities(track_index?, track_type?, item_index?)`
- `audio_mapping_report(clip_ids?)`
- `safe_auto_sync_audio(clip_ids|selected, settings?, dry_run?)` — `settings`
  accepts human-readable keys: `method`/`mode` (`waveform`|`timecode`),
  `channel` (`auto`|`mix`|int), `retain_embedded_audio`, `retain_video_metadata`.
  Unrecognized keys are dropped and echoed back in `ignored_settings` rather than
  silently failing the call.
- `transcription_capabilities(clip_ids?|selected?)`
- `subtitle_generation_probe(settings?, allow_generate?)` — `settings` accepts
  human-readable keys resolved to live `SUBTITLE_*`/`AUTO_CAPTION_*` enums:
  `language` (e.g. `english`, `korean`), `preset` (`default`|`teletext`|`netflix`),
  `line_break` (`single`|`double`), `chars_per_line` (1–60), `gap` (0–10).
  Unrecognized keys/values are dropped and echoed in `ignored_settings`; generation
  is read-back verified against the subtitle track count.
- `fairlight_boundary_report`

**`timeline_markers`** — Markers and playhead on the current timeline.

Key actions: `add(frame|frame_id|timecode?, color?, name?, note?, duration?)`, `get_all`,
`get_current_timecode`, `set_current_timecode(timecode)`,
`get_current_video_item`, `get_thumbnail`, `get_thumbnail_image`

Review Annotation kernel actions (v2.10.0+) add a unified review layer across
timeline, timeline item, and media pool item scopes: `annotation_capabilities`,
`probe_annotations`, `normalize_marker_payload`, `copy_annotations`,
`move_annotations`, `sync_marker_custom_data`, `clear_annotations_by_scope`,
`export_review_report`, and `annotation_boundary_report`. See
`docs/kernels/review-annotation-kernel.md` for the live-tested scope and boundary map.

For `add`, omit `frame`/`timecode` to create the marker at the current playhead.
The compound tool accepts `frame`, `frame_id`, and `frameId` aliases.

Note: `get_thumbnail` returns raw pixel data from `GetCurrentClipThumbnailImage()`.
The dictionary includes `data` (raw bytes as a Python bytes-like object),
`format`, `width`, `height`, `noOfComponents`, and `depth`. This reflects Resolve's processed
output — including color grading and effects — rather than the source file. It
is the CLIP's thumbnail, though: every frame of a clip returns the same image, so
it cannot verify a specific frame. Use `timeline_frame(action="capture")` for
that.

Use `get_thumbnail_image` when the MCP client can display image content directly.
It converts the same Resolve thumbnail payload to PNG bytes without writing a
file to disk. Both actions hold the Color page for the read, restore the
previous page, and poll rather than trusting a single read; both still need
Resolve to be the frontmost application. Prefer `timeline_frame(action="capture")`
for new work — it renders the frame you actually asked for.

**`timeline_frame`** — Capture a timeline frame as viewable image content.

Key actions: `capture(timecode?|frame?, quality?, max_width?, format?, timeline_name?)`,
`capabilities`

Returns MCP image content, so a multimodal assistant can look at what Resolve is
rendering — grade, Fusion, titles, transitions — rather than inferring it from
metadata. (For the raw camera file instead, use
`media_analysis(action="extract_frames")`.)

- `quality="frame"` (default) renders exactly that frame — the only
  frame-accurate route. Full resolution, well under a second, works headless.
  `preview` is the same render bounded to 1280px.
- `quality="thumbnail"` is instant and touches nothing, but returns the **clip's**
  thumbnail — identical for every frame of that clip. Use it to see which clip is
  under the playhead, never to judge a specific frame. Needs the Color page *and*
  Resolve frontmost.
- `quality="still"` uses a Gallery still; requires the Gallery panel to be open.
- `max_width` caps the width to conserve context (needs ffmpeg; without it the
  call fails rather than quietly returning a full-size frame). `format` is `jpg`
  (default), `png`, or `tif`.
- `timecode` accepts absolute (`01:00:15:12`) or elapsed (`00:00:15:12`) time;
  `frame` is the absolute timeline frame. Omit both to capture the playhead.

The playhead, page, current timeline and Gallery are restored. The render route
additionally touches project render settings: format and codec are restored and
the render job is deleted, but `TargetDir`/`CustomName`/mark range cannot be read
back on builds without `GetRenderSettings`, so they are reset to the full
timeline rather than restored. Reach for `quality="thumbnail"` when zero side
effects matter more than accuracy.

```
timeline_frame(action="capture", params={"timecode": "01:00:15:12", "max_width": 1280})
```

This tool is separate from `timeline` because a tool that returns image content
cannot declare a `Dict[str, Any]` output schema — FastMCP validates returns
against it, and image content fails that validation.

**`timeline_ai`** — AI/ML analysis on the current timeline.

Key actions: `create_subtitles(settings?)` (human-readable settings resolved to
`SUBTITLE_*`/`AUTO_CAPTION_*` enums + read-back verified — see
`subtitle_generation_probe`), `detect_scene_cuts`,
`grab_still`, `grab_all_stills(source?)`, `analyze_dolby_vision`

---

### Timeline Items

Timeline items are identified by `track_type`, `track_index`, and `item_index`
(all default to `"video"`, `1`, `0` respectively — the first clip on the first
video track). Always retrieve item IDs via `timeline.get_items` before operating
on specific items.

**`timeline_item`** — Properties, transform, speed, audio, keyframes.

Key actions:
- `get_property(key?)` / `set_property(key, value)` — raw property access
- `get_name` / `set_name(name)`
- `get_duration`, `get_start`, `get_end`
- `get_retime` / `set_retime(process?, motion_estimation?)`
  - process: `"nearest"`, `"frame_blend"`, `"optical_flow"` (or 0–3)
  - motion_estimation: integer 0–6
- `get_transform` / `set_transform(Pan?, Tilt?, ZoomX?, ZoomY?, RotationAngle?, ...)`
- `get_crop` / `set_crop(CropLeft?, CropRight?, CropTop?, CropBottom?, ...)`
- `get_composite` / `set_composite(Opacity?, CompositeMode?)`
- `get_audio` / `set_audio(Volume?, Pan?, AudioSyncOffset?)`
- `get_voice_isolation_state` / `set_voice_isolation_state(state)` — Resolve
  20.1+; audio timeline items only
- `get_keyframes(property)`, `add_keyframe(property, frame, value)`,
  `modify_keyframe`, `delete_keyframe`, `set_keyframe_interpolation`
  - interpolation values: `"Linear"`, `"Bezier"`, `"EaseIn"`, `"EaseOut"`, `"EaseInOut"`
- `get_unique_id` — use this to get the ID for other tool calls
- `get_media_pool_item` — get the source clip from the Media Pool

**`timeline_item_markers`** — Markers, flags, clip color on timeline items.

**`timeline_item_fusion`** — Fusion comp management on timeline items.

Key actions: `add_comp`, `get_comp_count`, `get_comp_names`, `export_comp(path, index)`,
`import_comp(path)`, `delete_comp(name)`, `load_comp(name)`, `rename_comp`,
`get_cache_enabled`, `set_cache(value)` — value: `"Auto"`, `"On"`, `"Off"`

**`timeline_item_color`** — Color grading on timeline items. Requires Color page
for most operations.

Key actions:
- `set_cdl(cdl)` — cdl: `{NodeIndex, Slope, Offset, Power, Saturation}`
  - Slope/Offset/Power can be arrays `[R, G, B]` or strings like `"1.0 1.0 1.0"`
- `add_version(name, type?)`, `load_version(name, type?)`, `get_version_names(type?)`
  - type: `0` = local, `1` = remote
- `assign_color_group(group_name)`, `remove_from_color_group`
- `export_lut(type, path)`
- `reset_all_node_colors` — Resolve 20.2+; resets node colors for the active
  clip version
- `stabilize`, `smart_reframe`
- `create_magic_mask(mode)` — mode: `"F"` forward, `"B"` backward, `"BI"` bidirectional
  (requires DaVinci Neural Engine and Color page). Magic Mask v2 isolates via
  operator CLICKS on the subject (manual ch. 139; strokes are legacy v1) and
  the API cannot place clicks — with none present this returns
  `{needs_hitl: true, hitl: {steps...}}` instead of a bare false. Never call it
  as if it isolates a subject unattended; prove any isolation with a rendered
  frame (`gallery_stills grab_and_export`).

Color / Grade kernel actions (v2.11.0+) add safer grade inspection and
boundary helpers: `grade_capabilities`, `probe_grade_item`,
`probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`, `safe_apply_drx`,
`safe_export_lut`, `grade_version_snapshot`, `grade_version_restore`,
`color_group_capabilities`, `gallery_capabilities`, and
`grade_boundary_report`. See `docs/kernels/color-grade-kernel.md` for the live-tested
support map, and `docs/guides/color-decision-guide.md` for the practical distinction
between direct API color controls and opaque full-grade artifacts.

**`timeline_item_takes`** — Take management.

Key actions: `add(clip_id, start_frame?, end_frame?)`, `get_count`,
`get_selected_index`, `select(index)`, `delete(index)`, `finalize`

---

### Gallery

**`gallery`** — Gallery album management.

Key actions: `get_still_albums`, `get_current_album`, `set_current_album(album_index)`,
`create_still_album`, `create_power_grade_album`

**`gallery_stills`** — Manage stills within an album. Requires Color page.

Key actions:
- `get_stills(album_index?)` — returns count
- `get_label(still_index)` / `set_label(still_index, label)`
- `import_stills(paths)` — paths to `.drx` files
- `export_stills(folder_path, prefix?, format?, album_index?)`
  - formats: `dpx`, `cin`, `tif`, `jpg`, `png`, `ppm`, `bmp`, `xpm`, `drx`
- `grab_and_export(folder_path, prefix?, format?, album_index?, cleanup?)` —
  grabs a still from the current frame and exports it in one atomic call.
  Returns `{files, format, folder, cleaned_up}` where each file entry includes
  `data_base64` for image files and `data` (text) for `.drx` grade files.
  `cleanup` defaults to `true` — files are deleted from disk after being inlined.
  Only files this call produced are removed: the export goes to a private
  staging directory inside `folder_path`, so anything else written there
  meanwhile is untouched, and `folder_path` itself is removed only if the call
  created it and left it empty. With `cleanup: false` the files are moved up
  into `folder_path` without overwriting anything already there.
  Requires Color page with Gallery panel visible.
- `delete_stills(still_indices)`

---

### Node Graphs

**`graph`** — Node graph operations on timeline, timeline item, or color group.

The `source` parameter controls which graph you target:
- `"timeline"` (default) — the timeline node graph
- `"item"` — a specific timeline item (needs `track_type`, `track_index`, `item_index`)
- `"color_group_pre"` / `"color_group_post"` — group pre/post graphs (needs `group_name`)

Key actions: `get_num_nodes(source?)`, `set_lut(node_index, lut_path, source?)`,
`get_lut(node_index, source?)`, `get_node_label(node_index, source?)`,
`set_node_enabled(node_index, enabled, source?)`,
`apply_grade_from_drx(path, grade_mode?, source?)` — grade_mode: `0`=no keyframes,
`1`=source timecode aligned, `2`=start frames aligned,
`reset_all_grades(source?)`

DRX-apply gotchas (also apply to `timeline_item_color.safe_apply_drx`): ALWAYS pass
`track_type`/`track_index`/`item_index` explicitly — the default target is video track 1
item 0, NOT the current clip — and grab a still/`.drx` backup first (`safe_apply_drx` does
not snapshot). When the applied `.drx` has the same node structure/ids as the target's
current graph, Resolve keeps the existing node-editor layout (positions in the `.drx` are
silently ignored); to re-layout a graph programmatically, reset the grade first, then
apply (see the advanced server's `drx` `relayout` and `api_truth`).

**`color_group`** — Manage color groups.

Key actions: `list`, `get_name(group_name)`, `set_name(group_name, new_name)`,
`get_clips(group_name)`, `get_pre_clip_graph(group_name)`,
`get_post_clip_graph(group_name)`

---

### Fusion

**`fusion_comp`** — Fusion composition node graph operations.

Target a comp either from a timeline item (pass `clip_id`, `timeline_item_id`, or
`timeline_item={track_type, track_index, item_index}`) or from the active Fusion
page comp (omit timeline scope).

READBACK IS NOT PROOF FOR FUSION PARAMETERS. Up to v2.98.4 every value write
here ran inside a `Comp.Lock()`, and a value written under a comp lock is stored
in the graph and returned by `get_input` while the RENDER ignores it entirely
(Studio 19.1.3.7: PSNR inf vs the no-comp baseline). Four of the six affected
paths — `set_input`, `safe_set_inputs`, `set_text_plus`, `add_fusion_mask` — were
confirmed broken by rendering; `bulk_set_inputs` and `bulk_set_expressions`
escape because they wrap their write in `StartUndo`/`EndUndo`. Fixed in v2.98.5,
mechanism settled in v2.98.8, and guarded by
`tests/test_fusion_value_write_lock.py` plus the rendered-frame harness
`tests/live_fusion_value_write_validation.py`. The lesson outlives the bug: a
Fusion parameter that reads back correctly has proven nothing about the output,
so confirm any Fusion look with a rendered frame (`gallery_stills
grab_and_export` or a frame from a delivered render), never with `get_input`.

Key actions:
- `add_tool(tool_type, x?, y?, name?)` — common types: `Merge`, `Background`,
  `TextPlus`, `Transform`, `Blur`, `ColorCorrector`, `RectangleMask`,
  `EllipseMask`, `Tracker`, `MediaIn`, `MediaOut`, `Glow`, `DeltaKeyer`,
  `UltraKeyer`, `FilmGrain`, `CornerPositioner`
- `delete_tool(tool_name)`, `get_tool_list(type?)`, `find_tool(name)`
- `connect(target_tool, input_name, source_tool, output_name?)`
- `disconnect(tool_name, input_name)`
- `set_input(tool_name, input_name, value, time?)` /
  `get_input(tool_name, input_name, time?)`
- `get_inputs(tool_name)` / `get_outputs(tool_name)`
- `set_attrs(tool_name, attrs)` / `get_attrs(tool_name)`
- `add_keyframe(tool_name, input_name, time, value)`
- `get_position(tool_name)` / `set_position(tool_name, x, y)` — read/write a node's
  position on the FlowView canvas; `set_position` returns a position read-back
- `copy_tool(tool_name, name?, x?, y?)` — duplicate a node (settings copied via a
  temp `.setting` file), optionally renaming and repositioning it
- `auto_arrange(tool_names?, direction?, spacing?, x?, y?)` — lay tools out in a row
  (`direction="horizontal"`, default) or column (`"vertical"`)
- `get_comp_info`, `set_frame_range(start, end)`, `get_frame_range`, `render`
- `start_undo(name?)` / `end_undo(keep?)`
- `bulk_set_inputs(ops)` — batch set inputs across multiple timeline item comps in
  one call; each op requires timeline scope plus `tool_name`, `input_name`, `value`
- `bulk_set_expressions(ops)` — batch attach expressions across multiple timeline
  item comps in one call; each op requires timeline scope plus `tool_name`,
  `input_name`, `expression`
- `group_settings_export(group_name, path, include_advisory?)` — write a
  `GroupOperator` to disk and return a parsed published-input summary
- `group_settings_splice_inputs(source_path, template_path, dest_path?, source_group_name?, template_group_name?)` —
  replace one `.setting` file's `Inputs = ordered() { ... }` block with the
  matching block from another, preserving inner tools and outer structure;
  balanced-brace parser handles nested `UserControls`
- `group_settings_load(group_name, settings_path, backup_path?, undo_name?)` —
  apply a `.setting` to a live group with an auto backup and an undo wrap so
  Ctrl+Z reverses the change

Fusion Composition kernel actions (v2.12.0+) add safer graph inspection and
mutation wrappers around the raw Fusion API:

- `fusion_graph_capabilities`
- `probe_fusion_comp(include_io?, max_tools?)`
- `probe_fusion_tool(tool_name, include_io?)`
- `safe_add_tool(tool_type, name?, dry_run?)`
- `safe_set_inputs(tool_name, inputs, readback?)`
- `safe_connect_tools(target_tool, input_name, source_tool, dry_run?)`
- `fusion_boundary_report(include_io?)`
- `add_fusion_mask(mask_type?, width?, height?, corner_radius?, center?|center_x?/center_y?,
  angle?, soft_edge?, border_width?, invert?, inputs?, connect_to?, connect_input?, readback?)`
  — one-call Rectangle/Ellipse mask (e.g. rounded corners): adds the mask tool, sets its
  params (0..1), and optionally wires it into `connect_to`'s mask input (`EffectMask` default).
- `set_text_plus(text, tool_name?, input_name?, readback?)` / `get_text_plus(tool_name?, input_name?)`
  — read/write the text of a Fusion `Text+` tool or Fusion title template (e.g. a "Deep"
  title). Auto-finds the `Text+` tool when `tool_name` is omitted; `input_name` defaults to
  `StyledText`. For non-Fusion generator titles, use `timeline(action="set_title_text")` instead.

---

### Render

**`render`** — Render pipeline: jobs, presets, formats, codecs.

Key actions: `add_job`, `list_jobs`, `delete_job(job_id)`, `delete_all_jobs`,
`start(job_ids?, interactive?)`, `stop`, `is_rendering`, `get_formats`,
`get_codecs(format)`, `set_format_and_codec(format, codec)`,
`get_resolutions(format, codec)`, `set_settings(settings)`,
`list_presets`, `load_preset(name)`, `save_preset(name)`,
`quick_export_presets`, `quick_export(preset, params?)`

Render / Deliver kernel actions (v2.9.0+) add planning and safety layers:
`render_capabilities`, `probe_render_matrix`, `probe_render_settings`,
`validate_render_settings`, `safe_set_render_settings`,
`prepare_render_job`, `render_job_lifecycle_probe`,
`quick_export_capabilities`, `safe_quick_export`, and
`export_render_boundary_report`. See `docs/kernels/render-deliver-kernel.md` for the
live-tested format/codec, settings, job, and Quick Export boundary map.

Delivery targets (v2.67.0+) are named render intents — `list_delivery_targets`,
`resolve_delivery_target(target)`, `prepare_delivery_job(target, target_dir)`.
Ask for `prores422hq_master`, `dnxhr_hqx_master`, `h264_1080p_web`, or a platform
alias like `youtube` / `tiktok`, and one definition supplies both the Resolve
render settings and the ffprobe QC spec the advanced server checks the output
against. Format/codec resolve against the live matrix, so a target this machine
or license cannot render fails with the available lists rather than silently
rendering something else. `list_delivery_targets` with `check_availability: true`
reports what this install can actually deliver.

---

## Common Workflows

### 1. Connect and verify

```
resolve_control(action="launch")
resolve_control(action="get_version")
resolve_control(action="mcp_update_status")
setup(action="get_defaults")
resolve_control(action="get_page")
```

Always call `launch` first in a new session. It is safe to call when Resolve is
already running.

Use `setup(action="schema")`, `setup(action="get_defaults")`, and
`setup(action="set_defaults")` when the user wants durable conversation
defaults for media analysis, metadata publishing, timed markers, report style,
or MCP update behavior. Setup defaults may shape future tool parameters, but
confirmed Resolve project writes still require the relevant action's explicit
confirmation flag.

### 2. Open a project and navigate timelines

```
project_manager(action="list")
project_manager(action="load", params={"name": "My Film"})
timeline(action="list")
timeline(action="set_current", params={"index": 2})
timeline(action="get_current")
```

### 3. Add clips to Media Pool and build a timeline

```
media_storage(action="get_volumes")
media_storage(action="import_to_pool", params={"items": ["/path/to/clip.mp4"]})
media_pool(action="get_current_folder")
media_pool(action="create_timeline", params={"name": "Assembly"})
media_pool(action="get_selected")
media_pool(action="append_to_timeline", params={"clip_ids": ["<uuid>", ...]})
media_pool(action="safe_import_sequence", params={
  "pattern": "/path/to/frames/shot_%04d.dpx",
  "start_index": 1001,
  "end_index": 1048,
  "target_folder": "Master/Plates"
})
media_pool(action="media_pool_boundary_report", params={"selected": True, "depth": 2})
# Positioned append (MediaPool.AppendToTimeline([{clipInfo}, ...])) — e.g. rebuild a subtitle row after delete_clips
media_pool(action="append_to_timeline", params={"clip_infos": [
  {"clip_id": "<uuid>", "start_frame": 0, "end_frame": 100, "record_frame": 1200, "track_index": 4}
]})
```

Mixed-fps caution: `start_frame`/`end_frame` are SOURCE frames, and a source
whose fps differs from the timeline's rounds DOWN on conversion — a 24.0 or
29.97 clip appended into a 23.976 timeline can land one frame short of its
slot. Plan durations in timeline frames, extend `end_frame` by a source frame
when the floor misses, and finish with `detect_gaps_overlaps` (see
`api_truth`). `import_media` always lands in the CURRENT bin — call
`set_current_folder` first; there is no destination parameter.

### 4. Inspect and annotate timeline items

```
timeline(action="get_items", params={"track_type": "video", "index": 1})
timeline(action="duplicate_clips", params={
  "clip_ids": ["<timeline-item-uuid>"], "target_track_index": 2, "record_frame_offset": 120
})
timeline(action="duplicate_clips", params={
  "selected": True,
  "placement": "track_above",
  "include_linked": True,
  "copy_properties": ["transform", "crop", "composite", "audio", "dynamic_zoom", "scaling", "stabilization", "clip_color", "markers", "enabled"],
  "copy_keyframes": True
})
timeline(action="probe_edit_kernel_item", params={"selected": True})
timeline(action="copy_range", params={
  "start_frame": 110, "end_frame": 130, "record_frame": 900,
  "track_types": ["video", "audio"], "target_track_index": 2
})
timeline_item(action="get_name", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item(action="get_property", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_markers(action="add", params={"color": "Blue", "note": "Review this"})
timeline_item_markers(action="add", params={"frame": 100, "color": "Blue", "name": "Review", "note": "Check this", "duration": 1, "track_type": "video", "track_index": 1, "item_index": 0})
```

For an exhaustive live boundary map of the timeline edit kernel, run:

```
python3.11 tests/live_duplicate_clips_validation.py --output-dir /tmp/timeline-kernel-probe
```

The live harness first validates duplicate/range edit behavior, then runs the
exhaustive probe. It creates disposable projects with synthetic media, emits
JSON and Markdown reports, and classifies each API surface as `supported`,
`partially_supported`, `read_only`, `write_only_unverifiable`,
`version_or_page_dependent`, `unsupported`, `not_applicable`, or `error`.
See `docs/kernels/timeline-edit-kernel.md` for the maintained support map and current
Resolve API limitations.

For the Media Pool / Ingest boundary map, run:

```
python3.11 tests/live_media_pool_ingest_validation.py --output-dir /tmp/media-pool-ingest-probe
```

The harness creates a disposable project, generates synthetic video/audio/still
and image-sequence fixtures, probes safe import/metadata/annotation/link
helpers, writes JSON and Markdown reports, deletes the project, and removes the
generated media directory. See `docs/kernels/media-pool-ingest-kernel.md`.

For the Review Annotation boundary map, run:

```
python3.11 tests/live_review_annotation_validation.py --output-dir /tmp/review-annotation-probe
```

The harness creates a disposable project, generates synthetic video/audio media,
probes timeline, timeline item, and media pool item marker/flag/color/report
behavior, writes JSON and Markdown reports, deletes the project, and removes the
generated media directory. See `docs/kernels/review-annotation-kernel.md`.

### 5. Color grading

```
resolve_control(action="open_page", params={"page": "color"})
timeline_item_color(action="set_cdl", params={"cdl": {"NodeIndex": 1, "Slope": [1.1, 1.0, 0.9], "Offset": [0.0, 0.0, 0.0], "Power": [1.0, 1.0, 1.0], "Saturation": 1.0}, "track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="add_version", params={"name": "Grade v2", "track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="grade_boundary_report", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="safe_export_lut", params={"type": "33ptcube", "path": "/tmp/look.cube", "track_type": "video", "track_index": 1, "item_index": 0})
```

For the Color / Grade boundary map, run:

```
python3.11 tests/live_color_grade_validation.py --output-dir /tmp/color-grade-probe
```

The harness creates a disposable project, generates synthetic color-bar media,
probes grade, node graph, version, copy, LUT, Gallery, and color-group
behavior, writes JSON and Markdown reports, deletes the project, and removes
generated media and exported probe files. See `docs/kernels/color-grade-kernel.md`.

### 6. Grab a still and read the grade data

```
resolve_control(action="open_page", params={"page": "color"})
gallery_stills(action="grab_and_export", params={"folder_path": "/tmp/stills", "format": "jpg"})
```

The response includes `files[].data_base64` (the image as base64) and
`files[].data` for the companion `.drx` grade file (plain text XML). The
image reflects the color-graded frame as Resolve sees it, not the raw source.

### 7. Export the timeline

```
timeline(action="export", params={"path": "/tmp/export.edl", "type": "EDL", "subtype": "CMX3600"})
timeline(action="export", params={"path": "/tmp/export.fcpxml", "type": "FCPXML"})
timeline(action="export_timeline_checked", params={"path": "/tmp/export.drt", "format": "drt"})
timeline(action="detect_gaps_overlaps")
timeline(action="conform_boundary_report", params={"handles": 8})
```

For the Timeline Conform / Interchange boundary map, run:

```
python3.11 tests/live_timeline_conform_validation.py --output-dir /tmp/timeline-conform-probe
```

The harness creates a disposable project, generates synthetic media, builds a
gapped timeline, probes structure, source ranges, gap/overlap detection,
interchange export/import/round-trip behavior, synthetic missing-media relink
planning, writes reports, deletes the project, and removes generated media.
See `docs/kernels/timeline-conform-interchange-kernel.md`.

For the Audio / Fairlight boundary map, run:

```
python3.11 tests/live_audio_fairlight_validation.py --output-dir /tmp/audio-fairlight-probe
```

The harness creates a disposable project, generates synthetic video and audio
media, probes track/item audio state, mappings, voice isolation, property
writes, auto-sync, transcription, subtitle generation, Fairlight preset listing,
audio insertion, writes reports, deletes the project, and removes generated
media. See `docs/kernels/audio-fairlight-kernel.md`.

### 8. Add and start a render job

```
render(action="get_formats")
render(action="probe_render_matrix")
render(action="set_format_and_codec", params={"format": "QuickTime", "codec": "H.265 Master"})
render(action="validate_render_settings", params={"settings": {"TargetDir": "/tmp/renders", "CustomName": "review", "SelectAllFrames": true}, "require_temp_target": true})
render(action="prepare_render_job", params={"target_dir": "/tmp/renders", "settings": {"CustomName": "review", "SelectAllFrames": true}})
render(action="add_job")
render(action="list_jobs")
render(action="start")
render(action="is_rendering")
```

For the Render / Deliver boundary map, run:

```
python3.11 tests/live_render_deliver_validation.py --output-dir /tmp/render-deliver-probe
```

The harness creates a disposable project, generates a synthetic timeline, probes
format/codec/resolution compatibility, validates settings, runs a tiny temp
render job, writes reports, deletes the project, and removes generated media and
render outputs.

### 9. Apply a Fusion effect to a timeline item

```
timeline_item_fusion(action="add_comp", params={"track_type": "video", "track_index": 1, "item_index": 0})
fusion_comp(action="add_tool", params={"tool_type": "Glow", "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
fusion_comp(action="set_input", params={"tool_name": "Glow1", "input_name": "Gain", "value": 0.8, "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
fusion_comp(action="fusion_boundary_report", params={"timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
```

For the Fusion Composition boundary map, run:

```
python3.11 tests/live_fusion_composition_validation.py --output-dir /tmp/fusion-composition-probe
```

The harness creates a disposable project, generates synthetic video media,
probes timeline item comp creation, safe tool creation, input writes, graph
inspection, connections, bulk writes, frame range, and comp export, writes
reports, deletes the project, and removes generated media. See
`docs/kernels/fusion-composition-kernel.md`.

---

## Error Handling and Recovery

| Error message | Cause | Fix |
|---|---|---|
| `"Not connected to DaVinci Resolve"` | Resolve is not running or scripting is disabled | Call `resolve_control(action="launch")`, wait, retry |
| `"No project open"` | No project is currently loaded | Call `project_manager(action="load", params={"name": "..."})` |
| `"No current timeline"` | Project has no timeline set as current | Call `timeline(action="set_current", params={"index": 1})` |
| `"No item at index N"` | `item_index` out of range for the track | Call `timeline(action="get_items", ...)` first to find valid indices |
| `"Clip not found"` | Stale or wrong `clip_id` | Re-fetch IDs via `media_pool(action="get_selected")` or `folder(action="get_clips")` |
| `"Gallery not available"` | Not on Color page | `resolve_control(action="open_page", params={"page": "color"})` |
| `"GrabStill failed"` | Not on Color page or no clip under playhead | Switch to Color page, move playhead over a clip |
| `"ExportStills failed"` | Gallery panel not open in UI | Instruct user to open Workspace > Gallery |
| `"Tool '...' not found"` | Wrong tool name in Fusion comp | Use `fusion_comp(action="get_tool_list")` to list available tools |
| `"Color group '...' not found"` | Group name mismatch | Use `color_group(action="list")` first |

When a tool returns `{"success": False}` without an error key, the underlying
Resolve API returned `False`. This usually means a precondition was not met
(wrong page, wrong state, context missing). Check the API reference in
`docs/reference/resolve_scripting_api.txt` for the specific method.

---

## Known Gotchas

**Resolve API object lifetimes** — Objects like timelines, clips, and color groups
returned by the API are live references that can become stale if the project state
changes (e.g., the user deletes a timeline). Always re-fetch IDs after any
destructive action.

**`SetName` on the active timeline** — `timeline(action="set_name")` returns
`False` if you try to rename the currently active timeline. Switch to a different
timeline first, rename, then switch back.

**`DeleteProject`** — Returns `False` if the project is currently open. Close it
first.

**CDL value format** — `set_cdl` accepts Slope/Offset/Power as arrays `[R, G, B]`,
tuples, or space-separated strings like `"1.0 1.0 1.0"`. All forms are normalized
internally.

**`GetNodeGraph(0)`** — Passing `0` as `layer_index` to `GetNodeGraph` on a
timeline item returns `False` in Resolve. Use `get_node_graph` without a
`layer_index` to get the default graph.

**Gallery export requires the Gallery panel visible** — `ExportStills` only works
if the Gallery panel is open in the Resolve UI on the Color page. Instruct the
user to open it via Workspace menu if export fails. Measured to fail in *both*
GUI (panel closed) and headless sessions, so a failure is not a reason to switch
modes. For pixels use `Project.ExportCurrentFrameAsStill`, which works in both.

**Python version** — the only hard requirement is Python **3.10+** (the MCP SDK
floor). There is no upper cap: 3.13/3.14 are accepted, and Python 3.14 is verified
working against Resolve Studio 20.3.2. On *older* Resolve builds the scripting
bridge may still fail to load on 3.13+ (`scriptapp("Resolve")` returns `None`);
`setup`/`doctor` warn on 3.13+ and their connection check surfaces a real failure.
If that happens, recreate the venv with Python 3.10–3.12 (the lowest-risk range).
The running server only warns on 3.13+ rather than exiting.

**Resolve version guards** — Resolve 20-specific actions return a clear
`requires DaVinci Resolve 20.x+` error when called against older builds. Resolve
19.1.3 remains the compatibility baseline; Resolve 20 additions were live-tested
on Resolve Studio 20.3.2.

**Source media integrity** — Do not transcode, convert, create proxies, or write
derivatives of source media unless the user explicitly asks. Analysis and tests
should write sidecars or synthetic fixtures, never modify camera originals.

**Windows multi-Python setups** — On Windows with multiple Python installations,
Resolve 20.3 may crash on import unless `PYTHONHOME` is set to the interpreter
used to build the venv. The installer handles this automatically; manual configs
may need it added.

**`item_index` is 0-based** — When specifying `item_index` in params, `0` is the
first item on the track, not `1`.

**`track_index` is 1-based** — Track indices start at `1`, not `0`.

**Fusion comp scope** — `fusion_comp` actions without a timeline scope target the
active composition on the Fusion page. If you intend to operate on a specific
clip's comp, always pass `clip_id`, `timeline_item_id`, or `timeline_item`.

---

## Seeing What Resolve Sees (Visual Context)

The server provides several mechanisms to inspect a frame as Resolve has processed
it, including color grading, effects, and compositing — not just the raw source
file.

WYSIWYG hierarchy (live-verified 2026-08-20): a `grab_and_export` gallery still
faithfully reflects edit sizing (Inspector transforms) and grades; media-pool
thumbnails and `thumbnail_contact_sheet` output do NOT reflect Fusion
composition output. Also note that whether an API-created Fusion comp is
honoured at render is Resolve-version-dependent: a wired comp rendered on
Studio 19.1.3.7, but on Studio 21.0.4 the same Blur configuration and a
Transform variant both rendered bit-identical to the no-comp baseline, and no
API selects an item's active composition (api_truth
'AddFusionComp'). The only acceptable proof of a Fusion or grade claim is a
rendered frame: `grab_and_export`, an exported gallery still, or a frame
extracted from a delivered render.

**Start here: `timeline_frame(action="capture")`** — Returns the frame at the
playhead (or at any `timecode`/`frame` you name) as MCP image content, so a
multimodal assistant can simply look at it. It renders that one frame, which is
what makes it frame-accurate; `max_width` bounds the context cost.

```
timeline_frame(action="capture", params={"timecode": "01:00:15:12", "max_width": 1280})
```

⚠️ **The thumbnail API is per-clip, not per-frame.** `GetCurrentClipThumbnailImage`
returns the same image for every frame of a given clip — verified by seeking
within one clip and getting byte-identical data, with the image changing only at
a clip boundary. It also returns nothing unless Resolve is the frontmost app.
Everything below is built on it, so none of it can confirm what a *specific*
frame looks like. Use `timeline_frame` for that.

**`timeline_markers(action="get_thumbnail")`** — Raw thumbnail data for the clip
under the playhead: `data`, `format`, `width`, `height`, `noOfComponents`,
`depth`. Use it when you need pixel data for tooling.

**`timeline_markers(action="get_thumbnail_image")`** — The same clip thumbnail as
image content; equivalent to `timeline_frame(action="capture", params={"quality":
"thumbnail"})`. Kept for existing callers.

**`timeline(action="thumbnail_contact_sheet")`** — A labeled PNG sheet written to
the analysis root. Because it samples the same API, it is effectively one image
per clip; treat it as a shot inventory, not as frame evidence.

**`gallery_stills(action="grab_and_export", params={...})`** — Grabs a still from
the current frame on the Color page and returns the image encoded as base64 in the
response (`files[].data_base64`). This is the most reliable way to get a
color-graded frame preview as a standard image format (jpg, tif, dpx, etc.)
that can be passed directly to a vision-capable AI model. Requires the Color page
with Gallery panel visible.

To use `grab_and_export` for visual inspection:

```
resolve_control(action="open_page", params={"page": "color"})
gallery_stills(action="grab_and_export", params={
  "folder_path": "/tmp/resolve-preview",
  "format": "jpg",
  "cleanup": true
})
```

The response `files[0].data_base64` is a standard JPEG, base64-encoded. Feed it
to a vision model to describe what Resolve is displaying — including all grading
and effects applied to the source.

---

## Clip ID Reference Pattern

Many tools require a `clip_id` (the UUID of a Media Pool clip) or a timeline item
identified by `track_type + track_index + item_index`. Use this pattern to resolve
both:

```
# List clips in the Media Pool
folder(action="get_clips")
# -> returns [{name, id}, ...]  — use id as clip_id

# List items on a timeline track
timeline(action="get_items", params={"track_type": "video", "index": 1})
# -> returns [{name, id, start, end, duration}, ...]
# Use track_type="video", track_index=1, item_index=<position in this list>
# Or use id to look up later via timeline_item(action="get_unique_id", ...)
```

---

## API Coverage

All 336 non-deprecated methods of the DaVinci Resolve Scripting API are covered.
331 methods have been live-tested across Resolve 19.1.3 Studio and Resolve
20.3.2 Studio. Five methods require infrastructure not available in typical
setups:

| Method | Requires |
|---|---|
| `ProjectManager.CreateCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.LoadCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.ImportCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.RestoreCloudProject` | Resolve cloud infrastructure |
| `Timeline.AnalyzeDolbyVision` | HDR / Dolby Vision content |

The full API reference is in `docs/reference/resolve_scripting_api.txt`.
